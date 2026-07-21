{ config, pkgs, ... }:
let
  stateDir = "${config.home.homeDirectory}/.local/share/szurubooru";
  podman = "${pkgs.podman}/bin/podman";
  # 2D videos from the NAS reach ~5 GB, above the 1 GiB defaults of both nginx
  # (client) and waitress (server), so raise the ceiling on both sides.
  maxUploadBytes = "8589934592";
  client = "szurubooru/client@sha256:74dedd54ca4f7c40ccf05be3768e813b47ed050326eab238f7e133d4acf87472";
  server = "szurubooru/server@sha256:a7ad796f36ec85d97f7869b3ec6808a8a2b0265e09be25f25af42c6b1ee40b54";
  postgres = "postgres@sha256:ea50b9fd617b66c9135816a4536cf6e0697d4eea7014a7194479c95f6edd5ef9";
in
{
  systemd.user.services.szurubooru = {
    Unit = {
      Description = "Szurubooru private media curation service";
      After = [ "podman.socket" ];
      Wants = [ "podman.socket" ];
    };

    Service = {
      Type = "exec";
      ExecStart = pkgs.writeShellScript "szurubooru-start" ''
        set -euo pipefail

        state_dir="${stateDir}"
        env_file="/run/secrets/szurubooru-env"
        runtime_dir="''${XDG_RUNTIME_DIR:?XDG_RUNTIME_DIR is required}/szurubooru"
        config_file="$runtime_dir/config.yaml"
        secret=""

        test -r "$env_file"
        mkdir -p "$state_dir/data" "$state_dir/sql" "$runtime_dir"
        chmod 700 "$runtime_dir"

        while IFS= read -r entry; do
          case "$entry" in
            SZURUBOORU_SECRET=*) secret="''${entry#SZURUBOORU_SECRET=}" ;;
          esac
        done < "$env_file"
        test -n "$secret"

        umask 077
        json_secret="$(${pkgs.jq}/bin/jq -Rn --arg secret "$secret" '$secret')"
        printf '%s\n' \
          'name: iris-booru' \
          'domain: https://ser7.taild4ba88.ts.net:8446' \
          "secret: $json_secret" \
          "" \
          '# Bootstrap closed after the first account was created.' \
          'default_rank: regular' \
          "" \
          'privileges:' \
          "    'users:create:self': administrator" \
          "    'posts:list': regular" \
          "    'posts:view': regular" \
          "    'posts:view:featured': regular" \
          "    'tags:list': regular" \
          "    'tags:view': regular" \
          "    'pools:list': regular" \
          "    'pools:view': regular" \
          > "$config_file"
        chmod 644 "$config_file"
        unset secret json_secret

        ${podman} pod rm --force --ignore szurubooru >/dev/null 2>&1 || true
        ${podman} pod create \
          --name szurubooru \
          --add-host server:127.0.0.1 \
          --publish 127.0.0.1:8086:80

        ${podman} create \
          --pod szurubooru \
          --name szurubooru-sql \
          --env-file "$env_file" \
          --volume "$state_dir/sql:/var/lib/postgresql/data:Z" \
          ${postgres}

        ${podman} create \
          --pod szurubooru \
          --name szurubooru-server \
          --env-file "$env_file" \
          --env POSTGRES_HOST=127.0.0.1 \
          --env THREADS=2 \
          --volume "$state_dir/data:/data:Z,U" \
          --volume "$config_file:/opt/app/config.yaml:ro,Z" \
          ${server} \
          /bin/sh -c \
          'cd /opt/app && alembic upgrade head && exec waitress-serve-3 \
             --listen "*:''${PORT}" --threads ''${THREADS} \
             --max-request-body-size ${maxUploadBytes} \
             szurubooru.facade:app'

        ${podman} create \
          --pod szurubooru \
          --name szurubooru-client \
          --env BACKEND_HOST=server \
          --env BASE_URL=/ \
          --volume "$state_dir/data:/data:ro,Z" \
          ${client} \
          /bin/sh -c \
          'sed -i "s/client_max_body_size [0-9]*;/client_max_body_size ${maxUploadBytes};/" \
             /etc/nginx/nginx.conf && exec /docker-start.sh'

        ${podman} start szurubooru-sql
        for _ in $(${pkgs.coreutils}/bin/seq 1 30); do
          if ${podman} exec szurubooru-sql pg_isready >/dev/null 2>&1; then
            break
          fi
          ${pkgs.coreutils}/bin/sleep 1
        done
        ${podman} exec szurubooru-sql pg_isready >/dev/null
        ${podman} start szurubooru-server
        exec ${podman} start --attach szurubooru-client
      '';
      ExecStop = "${podman} pod stop --ignore --time 30 szurubooru";
      ExecStopPost = "${podman} pod rm --force --ignore szurubooru";
      Restart = "always";
      RestartSec = "15s";
      TimeoutStopSec = "45s";
    };

    Install.WantedBy = [ "default.target" ];
  };
}
