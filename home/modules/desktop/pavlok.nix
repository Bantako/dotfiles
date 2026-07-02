{ pkgs, ... }:

let
  pavlok-stimulus = pkgs.writeShellScriptBin "pavlok-stimulus" ''
    exec ${pkgs.python3}/bin/python3 ${./scripts/pavlok-stimulus.py} "$@"
  '';
in
{
  home.packages = [ pavlok-stimulus ];

  systemd.user.services.bedtime-pavlok-vibe = {
    Unit = {
      Description = "Bedtime Pavlok vibration";
      After = [ "network-online.target" ];
      Wants = [ "network-online.target" ];
    };
    Service = {
      Type = "oneshot";
      ExecStart = "${pavlok-stimulus}/bin/pavlok-stimulus --type vibe --value 10 --reason bedtime-23:30";
    };
  };

  systemd.user.timers.bedtime-pavlok-vibe = {
    Unit.Description = "Bedtime Pavlok vibration timer";
    Install.WantedBy = [ "timers.target" ];
    Timer.OnCalendar = "*-*-* 23:30:00";
  };
}
