{ pkgs, config, lib, ... }:
let
  radicalePassword = lib.strings.removeSuffix "\n" (builtins.readFile /run/secrets/radicale-password);
in {
  home.packages = with pkgs; [
    vdirsyncer  # CalDAV ↔ ローカルファイル同期
    khal        # ターミナルカレンダー
  ];

  # vdirsyncer config
  xdg.configFile."vdirsyncer/config".text = ''
    [general]
    status_path = "${config.home.homeDirectory}/.local/share/vdirsyncer/status/"

    [pair radicale]
    a = "remote"
    b = "local"
    collections = ["from a", "from b"]

    [storage remote]
    type = "caldav"
    url = "http://192.168.0.222:5232"
    username = "morikawa"
    password = "${radicalePassword}"

    [storage local]
    type = "filesystem"
    path = "${config.home.homeDirectory}/.local/share/calendars/"
    fileext = ".ics"
  '';

  # khal config
  xdg.configFile."khal/config".text = ''
    [calendars]
    [[radicale]]
    path = ${config.home.homeDirectory}/.local/share/calendars/9ca8a0c6-1a90-3e7b-7ffe-d33e4edbad95/
    color = "dark blue"

    [locale]
    timeformat = %H:%M
    dateformat = %Y-%m-%d
    longdateformat = %Y-%m-%d %H:%M
    firstweekday = 1
    local_timezone = Asia/Tokyo

    [default]
    highlight_event_days = True
  '';

  # 定時同期（15分ごと）
  systemd.user.services.vdirsyncer-sync = {
    Unit = {
      Description = "vdirsyncer CalDAV sync";
    };
    Service = {
      Type = "oneshot";
      ExecStart = "${pkgs.vdirsyncer}/bin/vdirsyncer sync";
    };
  };

  systemd.user.timers.vdirsyncer-sync = {
    Unit = {
      Description = "vdirsyncer periodic sync";
    };
    Timer = {
      OnCalendar = "*:0/15";
      Persistent = true;
    };
    Install = {
      WantedBy = ["timers.target"];
    };
  };
}