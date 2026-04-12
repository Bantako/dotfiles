{pkgs, ...}: {
  home.packages = [ pkgs.jellyfin-mpv-shim ];

  # グラフィカルセッション開始後に自動起動
  systemd.user.services.jellyfin-mpv-shim = {
    Unit = {
      Description = "Jellyfin MPV Shim";
      After = [ "graphical-session.target" ];
    };
    Service = {
      ExecStart = "${pkgs.jellyfin-mpv-shim}/bin/jellyfin-mpv-shim";
      Restart = "on-failure";
    };
    Install = {
      WantedBy = [ "graphical-session.target" ];
    };
  };
}
