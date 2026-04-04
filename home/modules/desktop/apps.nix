{pkgs, ...}: {
  # Spotify TUI
  programs.ncspot.enable = true;

  # OBS
  programs.obs-studio.enable = true;

  home.packages = with pkgs; [
    discord
    discord-ptb
    totem # ビデオプレーヤー
    evince # PDFビューアー
    parsec-bin # 超速いリモートデスクトップクライアント
    remmina # VNCクライアント
    slack
    spotify
    prismlauncher # minecraft
    mpv
    featherpad # 軽量エディタ
  ];
}
