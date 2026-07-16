{ pkgs, ... }:
{
  # Karakeep itself is a rootless Podman user service. Keep its HTTP listener on
  # loopback and expose it only through Tailscale Serve.
  systemd.services.karakeep-tailscale-serve = {
    description = "Tailscale Serve for Karakeep";
    wants = [ "tailscaled.service" ];
    after = [
      "tailscaled.service"
      "home-manager-morikawa.service"
    ];
    wantedBy = [ "multi-user.target" ];

    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${pkgs.tailscale}/bin/tailscale serve --bg --yes --https=8444 http://127.0.0.1:3003";
    };
  };
}
