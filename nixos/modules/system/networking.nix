{ config, pkgs, ... }:

{
  networking.networkmanager.enable = true;

  # Configure network proxy if necessary
  # networking.proxy.default = "http://user:password@proxy:port/";
  # networking.proxy.noProxy = "127.0.0.1,localhost,internal.domain";

  # Some programs need SUID wrappers, can be configured further or are
  # started in user sessions.
  # programs.mtr.enable = true;
  # programs.gnupg.agent = {
  #   enable = true;
  #   enableSSHSupport = true;
  # };

  services.tailscale.enable = true;

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
