{ config, pkgs, ... }:

{
  networking.networkmanager.enable = true;

  services.logind.settings.Login = {
    IdleAction = "ignore";
    IdleActionSec = 0;
  };

  services.tailscale.enable = true;

  services.resolved.enable = true;

  services.syncthing = {
    enable = true;
    user = "morikawa";
    dataDir = "/home/morikawa";
    configDir = "/home/morikawa/.config/syncthing";
    openDefaultPorts = true;  # 22000/TCP+UDP, 21027/UDP
  };

  networking.firewall = rec {
    enable = true;
    trustedInterfaces = ["tailscale0"];
    allowedUDPPorts = [ config.services.tailscale.port ];

    # kdeconnect
    allowedTCPPortRanges = [ { from = 1714; to = 1764; } ];
    allowedUDPPortRanges = allowedTCPPortRanges;
  };
}
