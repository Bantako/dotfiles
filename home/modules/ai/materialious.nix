{ config, pkgs, ... }:
let
  stateDir = "${config.home.homeDirectory}/.local/share/materialious";
  podman = "${pkgs.podman}/bin/podman";
  # Materialious 1.17.3, amd64 manifest digest verified against Docker Hub on 2026-07-18.
  materialious = "docker.io/wardpearce/materialious-full@sha256:82a1749a09beee6781cf66df62775b642f67f13cc88b41abc345c29b1fd7532d";
in
{
  # The service is deliberately user-scoped, like Karakeep and Miniflux. It
  # listens only on loopback; the paired system unit exposes it through
  # Tailscale Serve over tailnet-only HTTPS.
  systemd.user.services.materialious = {
    Unit = {
      Description = "Materialious quiet YouTube client";
      After = [ "podman.socket" ];
      Wants = [ "podman.socket" ];
    };

    Service = {
      Type = "exec";
      ExecStart = pkgs.writeShellScript "materialious-start" ''
        set -euo pipefail

        state_dir="${stateDir}"
        env_file="/run/secrets/materialious-env"

        test -r "$env_file"
        umask 077
        mkdir -p "$state_dir/dumps"
        chmod 700 "$state_dir" "$state_dir/dumps"

        ${podman} rm --force --ignore materialious >/dev/null 2>&1 || true
        ${podman} create \
          --name materialious \
          --publish 127.0.0.1:3000:3000 \
          --env-file "$env_file" \
          --volume "$state_dir:/materialious-data:Z" \
          --security-opt no-new-privileges \
          ${materialious}

        exec ${podman} start --attach materialious
      '';
      ExecStop = "${podman} stop --ignore --time 30 materialious";
      ExecStopPost = "${podman} rm --force --ignore materialious";
      Restart = "on-failure";
      RestartSec = "15s";
      TimeoutStopSec = "45s";
    };

    Install.WantedBy = [ "default.target" ];
  };
}
