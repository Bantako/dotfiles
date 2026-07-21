{ config, pkgs, ... }:
let
  stateDir = "${config.home.homeDirectory}/.local/share/grimmory";
  podman = "${pkgs.podman}/bin/podman";
  # BookLore successor; digests verified against the registries on 2026-07-21.
  app = "ghcr.io/grimmory-tools/grimmory:latest";
  mariadb = "lscr.io/linuxserver/mariadb:11.4.5";
  # NAS book library, mounted read-only over CIFS (see mnt-ugreen.mount).
  booksDir = "/mnt/ugreen/data/books";
in
{
  # User-scoped rootless Podman pod, like Szurubooru/Materialious. Listens only
  # on loopback; the paired system unit exposes it through Tailscale Serve.
  systemd.user.services.grimmory = {
    Unit = {
      Description = "Grimmory self-hosted book library (BookLore successor)";
      After = [
        "podman.socket"
        "mnt-ugreen.mount"
      ];
      Wants = [ "podman.socket" ];
      # Do not start until the NAS library is actually mounted.
      RequiresMountsFor = booksDir;
    };

    Service = {
      Type = "exec";
      ExecStart = pkgs.writeShellScript "grimmory-start" ''
        set -euo pipefail

        state_dir="${stateDir}"
        pw_file="/run/secrets/grimmory-db-password"
        test -r "$pw_file"
        db_pw="$(${pkgs.coreutils}/bin/cat "$pw_file")"

        umask 077
        mkdir -p "$state_dir/data" "$state_dir/mariadb" "$state_dir/bookdrop"

        ${podman} pod rm --force --ignore grimmory >/dev/null 2>&1 || true
        ${podman} pod create \
          --name grimmory \
          --publish 127.0.0.1:6060:6060

        ${podman} create \
          --pod grimmory \
          --name grimmory-db \
          --env PUID=1000 --env PGID=1000 --env TZ=Asia/Tokyo \
          --env MYSQL_ROOT_PASSWORD="$db_pw" \
          --env MYSQL_DATABASE=grimmory \
          --env MYSQL_USER=grimmory \
          --env MYSQL_PASSWORD="$db_pw" \
          --volume "$state_dir/mariadb:/config:Z" \
          ${mariadb}

        ${podman} create \
          --pod grimmory \
          --name grimmory-app \
          --env USER_ID=1000 --env GROUP_ID=1000 --env TZ=Asia/Tokyo \
          --env DATABASE_URL="jdbc:mariadb://127.0.0.1:3306/grimmory" \
          --env DATABASE_USERNAME=grimmory \
          --env DATABASE_PASSWORD="$db_pw" \
          --env DISK_TYPE=NETWORK \
          --volume "$state_dir/data:/app/data:Z" \
          --volume "${booksDir}:/books:ro" \
          --volume "$state_dir/bookdrop:/bookdrop:Z" \
          --security-opt no-new-privileges \
          ${app}

        unset db_pw

        ${podman} pod start grimmory
        # keep the unit in the foreground on the app container
        exec ${podman} wait grimmory-app
      '';
      ExecStop = "${podman} pod stop --ignore --time 30 grimmory";
      ExecStopPost = "${podman} pod rm --force --ignore grimmory";
      Restart = "on-failure";
      RestartSec = "15s";
      TimeoutStopSec = "45s";
    };

    Install.WantedBy = [ "default.target" ];
  };
}
