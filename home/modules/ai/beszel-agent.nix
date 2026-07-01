{ config, pkgs, ... }:

{
  systemd.user.services.beszel-agent = {
    Unit = {
      Description = "Beszel agent";
      After = [
        "network-online.target"
        "podman.socket"
      ];
      Wants = [
        "network-online.target"
        "podman.socket"
      ];
    };

    Service = {
      Type = "exec";
      ExecStart = pkgs.writeShellScript "beszel-agent-start" ''
        set -euo pipefail

        state_dir="${config.home.homeDirectory}/.local/share/beszel-agent"
        env_file="$state_dir/.env"
        data_dir="$state_dir/data"
        podman_socket="/run/user/1000/podman/podman.sock"

        mkdir -p "$data_dir"

        if ! [ -f "$env_file" ]; then
          echo "Missing Beszel agent env file: $env_file" >&2
          exit 1
        fi

        if ! [ -S "$podman_socket" ]; then
          echo "Missing Podman socket: $podman_socket" >&2
          exit 1
        fi

        ${pkgs.podman}/bin/podman rm -f beszel-agent >/dev/null 2>&1 || true

        exec ${pkgs.podman}/bin/podman run --rm \
          --name beszel-agent \
          --network host \
          --env-file "$env_file" \
          -e HUB_URL=http://dxp2800-ad69.taild4ba88.ts.net:8092 \
          -e LISTEN=45876 \
          -v "$data_dir:/var/lib/beszel-agent" \
          -v "$podman_socket:$podman_socket:ro" \
          docker.io/henrygd/beszel-agent:latest
      '';
      ExecStop = "${pkgs.podman}/bin/podman stop beszel-agent";
      Restart = "on-failure";
      RestartSec = "15s";
      TimeoutStopSec = "30s";
    };

    Install.WantedBy = [ "default.target" ];
  };
}
