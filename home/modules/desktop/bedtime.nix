{ pkgs, ... }: {
  systemd.user.services.bedtime-lock = {
    Unit = {
      Description = "Bedtime screen lock";
      After = "graphical-session.target";
    };
    Service = {
      Type = "oneshot";
      ExecStart = "${pkgs.systemd}/bin/loginctl lock-session";
    };
  };

  systemd.user.timers.bedtime-lock = {
    Unit.Description = "Bedtime lock timer";
    Install.WantedBy = [ "timers.target" ];
    Timer.OnCalendar = [
      "*-*-* 23:30:00"
      "*-*-* 00:00:00"
      "*-*-* 01:00:00"
      "*-*-* 02:00:00"
    ];
  };

  systemd.user.services.bedtime-warn = {
    Unit = {
      Description = "Bedtime warning notification";
      After = "graphical-session.target";
    };
    Service = {
      Type = "oneshot";
      ExecStart = "${pkgs.libnotify}/bin/notify-send --urgency=critical --expire-time=30000 '就寝15分前' 'あと15分で自動ロックします'";
    };
  };

  systemd.user.timers.bedtime-warn = {
    Unit.Description = "Bedtime warning timer";
    Install.WantedBy = [ "timers.target" ];
    Timer.OnCalendar = "*-*-* 23:15:00";
  };
}
