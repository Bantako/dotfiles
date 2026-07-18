{ pkgs, ... }:
{
  # Materialious is a rootless Podman user service. Keep its HTTP listener on
  # loopback and expose it only through Tailscale Serve.
  systemd.services.materialious-tailscale-serve = {
    description = "Tailscale Serve for Materialious";
    wants = [ "tailscaled.service" ];
    after = [
      "tailscaled.service"
      "home-manager-morikawa.service"
    ];
    wantedBy = [ "multi-user.target" ];

    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${pkgs.tailscale}/bin/tailscale serve --bg --yes --https=8447 http://127.0.0.1:3000";
    };
  };
}
