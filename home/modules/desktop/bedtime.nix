{ pkgs, ... }: {
  systemd.user.services.bedtime-lock = {
    description = "Bedtime screen lock";
    after = [ "graphical-session.target" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${pkgs.systemd}/bin/loginctl lock-session";
    };
  };

  systemd.user.timers.bedtime-lock = {
    description = "Bedtime lock timer";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = [
        "*-*-* 23:30:00"
        "*-*-* 00:00:00"
        "*-*-* 01:00:00"
        "*-*-* 02:00:00"
      ];
      Persistent = false;
    };
  };

  systemd.user.services.bedtime-warn = {
    description = "Bedtime warning notification";
    after = [ "graphical-session.target" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${pkgs.libnotify}/bin/notify-send --urgency=critical --expire-time=30000 '就寝15分前' 'あと15分で自動ロックします'";
    };
  };

  systemd.user.timers.bedtime-warn = {
    description = "Bedtime warning timer";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* 23:15:00";
      Persistent = false;
    };
  };
}
