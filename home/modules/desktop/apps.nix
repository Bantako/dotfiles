{pkgs, lib, ...}: {
  # openldap-2.6.13 のテストがタイムアウトで失敗する（nixpkgs-unstable の一時的な問題）
  nixpkgs.overlays = [
    (final: prev: {
      openldap = prev.openldap.overrideAttrs (_: { doCheck = false; });
    })
  ];
  # Spotify TUI
  programs.ncspot.enable = true;

  # OBS
  programs.obs-studio.enable = true;

  home.packages = with pkgs; [
    # デスクトップ基盤
    alacritty          # サブターミナル
    fuzzel             # アプリランチャー
    nemo               # ファイルマネージャー
    xwayland-satellite # XWayland統合

    # エンタメ・コミュニケーション
    discord
    discord-ptb
    parsec-bin         # 超速いリモートデスクトップクライアント
    prismlauncher      # Minecraft
    remmina            # VNCクライアント
    slack
    spotify
    totem              # ビデオプレーヤー

    # メディア・ノート
    android-studio
    calibre            # 電子書籍管理
    electron           # Obsidian CLI の実行に必要
    obsidian           # ノート

    # Windows ゲーム
    bottles            # Wine フロントエンド（フリーゲーム等の exe 実行用）
    easyrpg-player     # RPG ツクール 2000/2003 のネイティブ Linux 実装

    # その他
    evince             # PDFビューアー（GNOME）
    featherpad         # 軽量エディタ
  ];
}
