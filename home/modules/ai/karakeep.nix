{ config, pkgs, ... }:
let
  stateDir = "${config.home.homeDirectory}/.local/share/karakeep";
  podman = "${pkgs.podman}/bin/podman";
  karakeep = "ghcr.io/karakeep-app/karakeep@sha256:64d6a9bbf2d37b5c808cf06b5d87f1f1c7846fdd3844724145a9741aeb06fd31";
  meilisearch = "getmeili/meilisearch@sha256:860fa4baed04ae1c235de870edab0c8006227546dea1bbb6411fbfc5e27cf1db";
  chrome = "gcr.io/zenika-hub/alpine-chrome@sha256:1a0046448e0bb6c275c88f86e01faf0de62b02ec8572901256ada0a8c08be23f";
in
{
  systemd.user.services.karakeep = {
    Unit = {
      Description = "Karakeep bookmark manager";
      After = [ "podman.socket" ];
      Wants = [ "podman.socket" ];
    };

    Service = {
      Type = "exec";
      ExecStart = pkgs.writeShellScript "karakeep-start" ''
        set -euo pipefail

        state_dir="${stateDir}"
        env_file="/run/secrets/karakeep-env"

        test -r "$env_file"
        mkdir -p "$state_dir/web" "$state_dir/meilisearch"

        ${podman} pod rm --force karakeep >/dev/null 2>&1 || true
        ${podman} pod create --name karakeep --publish 127.0.0.1:3003:3000

        ${podman} create \
          --pod karakeep \
          --name karakeep-chrome \
          ${chrome} \
          --no-sandbox \
          --disable-gpu \
          --disable-dev-shm-usage \
          --remote-debugging-address=0.0.0.0 \
          --remote-debugging-port=9222 \
          --hide-scrollbars

        ${podman} create \
          --pod karakeep \
          --name karakeep-meilisearch \
          --env-file "$env_file" \
          --env MEILI_HTTP_ADDR=0.0.0.0:7700 \
          --env MEILI_NO_ANALYTICS=true \
          --volume "$state_dir/meilisearch:/meili_data:Z" \
          ${meilisearch}

        ${podman} create \
          --pod karakeep \
          --name karakeep-web \
          --env-file "$env_file" \
          --env PORT=3000 \
          --env DATA_DIR=/data \
          --env MEILI_ADDR=http://127.0.0.1:7700 \
          --env BROWSER_WEB_URL=http://127.0.0.1:9222 \
          --env NEXTAUTH_URL_INTERNAL=http://127.0.0.1:3000 \
          --volume "$state_dir/web:/data:Z" \
          ${karakeep}

        ${podman} start karakeep-chrome karakeep-meilisearch
        exec ${podman} start --attach karakeep-web
      '';
      ExecStop = "${podman} pod stop --ignore --time 30 karakeep";
      ExecStopPost = "${podman} pod rm --force --ignore karakeep";
      Restart = "on-failure";
      RestartSec = "15s";
      TimeoutStopSec = "45s";
    };

    Install.WantedBy = [ "default.target" ];
  };
}
