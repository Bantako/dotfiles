{ config, pkgs, ... }:
let
  stateDir = "${config.home.homeDirectory}/.local/share/miniflux";
  podman = "${pkgs.podman}/bin/podman";
  miniflux = "miniflux/miniflux@sha256:42f14382a035e9d9bbc33910ca53f72d47177f75c3c638d2c5a85adf5582d538";
  postgres = "postgres@sha256:e013e867e712fec275706a6c51c966f0bb0c93cfa8f51000f85a15f9865a28cb";
in
{
  systemd.user.services.miniflux = {
    Unit = {
      Description = "Miniflux RSS reader";
      After = [ "podman.socket" ];
      Wants = [ "podman.socket" ];
    };

    Service = {
      Type = "exec";
      ExecStart = pkgs.writeShellScript "miniflux-start" ''
        set -euo pipefail

        state_dir="${stateDir}"
        env_file="/run/secrets/miniflux-env"

        test -r "$env_file"
        mkdir -p "$state_dir/postgres"

        ${podman} pod rm --force miniflux >/dev/null 2>&1 || true
        ${podman} pod create --name miniflux --publish 127.0.0.1:8084:8080

        ${podman} create \
          --pod miniflux \
          --name miniflux-db \
          --env-file "$env_file" \
          --volume "$state_dir/postgres:/var/lib/postgresql/data:Z" \
          ${postgres}

        ${podman} create \
          --pod miniflux \
          --name miniflux-web \
          --env-file "$env_file" \
          ${miniflux}

        ${podman} start miniflux-db
        for _ in $(${pkgs.coreutils}/bin/seq 1 30); do
          if ${podman} exec miniflux-db pg_isready -U miniflux >/dev/null 2>&1; then
            break
          fi
          ${pkgs.coreutils}/bin/sleep 1
        done
        ${podman} exec miniflux-db pg_isready -U miniflux >/dev/null
        exec ${podman} start --attach miniflux-web
      '';
      ExecStop = "${podman} pod stop --ignore --time 30 miniflux";
      ExecStopPost = "${podman} pod rm --force --ignore miniflux";
      Restart = "on-failure";
      RestartSec = "15s";
      TimeoutStopSec = "45s";
    };

    Install.WantedBy = [ "default.target" ];
  };
}
