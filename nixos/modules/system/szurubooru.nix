{ pkgs, ... }:
{
  # Szurubooru itself is a rootless Podman user service. Keep its HTTP listener
  # on loopback and expose it only through a dedicated Tailscale Serve port.
  systemd.services.szurubooru-tailscale-serve = {
    description = "Tailscale Serve for Szurubooru";
    wants = [ "tailscaled.service" ];
    after = [
      "tailscaled.service"
      "home-manager-morikawa.service"
    ];
    wantedBy = [ "multi-user.target" ];

    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${pkgs.tailscale}/bin/tailscale serve --bg --yes --https=8446 http://127.0.0.1:8086";
    };
  };
}
