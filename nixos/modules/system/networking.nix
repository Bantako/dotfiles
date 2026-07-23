{ config, pkgs, ... }:

let
  tailscaleServeUnits = [
    "grimmory-tailscale-serve"
    "iris-news-tailscale-serve"
    "karakeep-tailscale-serve"
    "miniflux-tailscale-serve"
    "n8n-tailscale-serve"
    "szurubooru-tailscale-serve"
  ];
  waitForTailscaled = pkgs.writeShellScript "wait-for-tailscaled" ''
    set -eu
    for _ in $(${pkgs.coreutils}/bin/seq 1 30); do
      if ${pkgs.tailscale}/bin/tailscale status --json \
        | ${pkgs.jq}/bin/jq -e '.BackendState == "Running"' > /dev/null; then
        exit 0
      fi
      ${pkgs.coreutils}/bin/sleep 1
    done
    echo "tailscaled did not reach Running within 30 seconds" >&2
    exit 1
  '';
in
{
  networking.networkmanager.enable = true;
  # tailscaled が systemd-resolved に直接 DNS を設定するため、NetworkManager が
  # tailscale0 を "external" 接続として二重管理すると major link change のたびに
  # DNS 設定が競合し MagicDNS が壊れる (tailscaled ログの nm-safe=no はこの非互換を示す)。
  networking.networkmanager.unmanaged = [ "interface-name:tailscale0" ];

  services.logind.settings.Login = {
    IdleAction = "ignore";
    IdleActionSec = 0;
  };

  services.tailscale.enable = true;

  # `After=tailscaled.service` only guarantees that the daemon process started;
  # after a system switch its local state may still be unavailable (NoState).
  # Gate every node-local Serve unit on the daemon reaching its Running state.
  systemd.services =
    builtins.listToAttrs (
      map (name: {
        inherit name;
        value.serviceConfig.ExecStartPre = waitForTailscaled;
      }) tailscaleServeUnits
    )
    // {
      # Expose Hermes WebUI as a Tailscale-only HTTPS PWA endpoint:
      #   https://ser7.taild4ba88.ts.net/ -> http://127.0.0.1:8787/
      # NixOS' services.tailscale.serve module configures Tailscale Services
      # (svc:<name>), not the node-local Serve endpoint, so use the CLI directly.
      hermes-webui-tailscale-serve = {
        description = "Tailscale Serve for Hermes WebUI";
        wants = [ "tailscaled.service" ];
        after = [ "tailscaled.service" ];
        wantedBy = [ "multi-user.target" ];

        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          ExecStartPre = waitForTailscaled;
          ExecStart = "${pkgs.tailscale}/bin/tailscale serve --bg --yes --https=443 http://127.0.0.1:8787";
        };
      };
    };

  services.resolved.enable = true;

  services.syncthing = {
    enable = true;
    user = "morikawa";
    dataDir = "/home/morikawa";
    configDir = "/home/morikawa/.config/syncthing";
    openDefaultPorts = true; # 22000/TCP+UDP, 21027/UDP
  };

  networking.firewall = rec {
    enable = true;
    trustedInterfaces = [ "tailscale0" ];
    allowedUDPPorts = [
      config.services.tailscale.port
      53317
    ];

    # kdeconnect
    allowedTCPPortRanges = [
      {
        from = 1714;
        to = 1764;
      }
    ];
    allowedUDPPortRanges = allowedTCPPortRanges;

    # localsend (LAN file transfer, mDNS discovery + data)
    allowedTCPPorts = [ 53317 ];
  };
}
