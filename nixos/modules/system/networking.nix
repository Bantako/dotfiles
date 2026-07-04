{ config, pkgs, ... }:

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

  # Expose Hermes WebUI as a Tailscale-only HTTPS PWA endpoint:
  #   https://ser7.taild4ba88.ts.net/ -> http://127.0.0.1:8787/
  # NixOS' services.tailscale.serve module configures Tailscale Services
  # (svc:<name>), not the node-local Serve endpoint, so use the CLI directly.
  systemd.services.hermes-webui-tailscale-serve = {
    description = "Tailscale Serve for Hermes WebUI";
    wants = [ "tailscaled.service" ];
    after = [ "tailscaled.service" ];
    wantedBy = [ "multi-user.target" ];

    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${pkgs.tailscale}/bin/tailscale serve --bg --yes --https=443 http://127.0.0.1:8787";
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
