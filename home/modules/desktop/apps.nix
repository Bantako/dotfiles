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
    alacritty          # フォールバックターミナル (ghostty障害時)
    fuzzel             # アプリランチャー
    nemo               # ファイルマネージャー
    xwayland-satellite # XWayland統合

    # エンタメ・コミュニケーション
    discord
    discord-ptb
    prismlauncher      # Minecraft
    slack
    spotify

    # メディア・ノート
    android-studio
    calibre            # 電子書籍管理
    electron           # Obsidian CLI の実行に必要
    obsidian           # ノート

    # その他
    featherpad         # 軽量エディタ
  ];
}
