{ config, pkgs, ... }:

let
  noctalia-state-bridge = pkgs.writeShellScriptBin "noctalia-state-bridge" ''
    exec ${pkgs.python3}/bin/python3 ${./scripts/noctalia-state-bridge.py} \
      --noctalia ${config.programs.noctalia-shell.package}/bin/noctalia-shell \
      "$@"
  '';
in
{
  systemd.user.services.noctalia-state-bridge = {
    Unit = {
      Description = "Read-only Noctalia state bridge for local automation";
      After = [ "graphical-session.target" ];
      PartOf = [ "graphical-session.target" ];
    };
    Service = {
      Type = "simple";
      ExecStart = "${noctalia-state-bridge}/bin/noctalia-state-bridge --host 127.0.0.1 --port 18765";
      Restart = "on-failure";
      RestartSec = 2;
      Environment = [ "WAYLAND_DISPLAY=wayland-1" ];
    };
    Install.WantedBy = [ "default.target" ];
  };
}
