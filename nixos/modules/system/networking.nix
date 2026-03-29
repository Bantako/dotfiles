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

  # Enable the OpenSSH daemon.
  # services.openssh.enable = true;

  services.tailscale.enable = true;
  networking.firewall = rec {
    enable = true;
    trustedInterfaces = ["tailscale0"];
    allowedUDPPorts = [ config.services.tailscale.port ];

    # kdeconnect
    allowedTCPPortRanges = [ { from = 1714; to = 1764; } ];
    allowedUDPPortRanges = allowedTCPPortRanges;
  };

  systemd.services."NetworkManager-wait-online".enable = false;
  systemd.services.disable-offload = {
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = ''
        /run/current-system/sw/bin/ethtool -K enp2s0 tso off gso off gro off
      '';
    };
  };
}
