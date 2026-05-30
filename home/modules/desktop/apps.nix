{pkgs, ...}: {
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

    # Wayland ユーティリティ
    satty              # スクショ加筆ツール（grim | satty でパイプ）
    grim               # Wayland スクリーンショット取得
    slurp              # 範囲選択（grim と組み合わせ）
    hyprpicker         # カラーピッカー（HEX を wl-copy）

    # エンタメ・コミュニケーション
    discord-ptb
    prismlauncher      # Minecraft
    slack
    spotify

    # メディア・ノート
    android-studio
    calibre            # 電子書籍管理
    obsidian           # ノート

    # ゲーミング
    mangohud           # FPS/温度/CPU使用率オーバーレイ
    protonup-qt        # GE-Proton等カスタムProton導入GUI
    protontricks       # Proton prefixにwinetricksを当てる

    # その他
    featherpad         # 汎用GUIテキストエディタ（コード=nvim、ノート=Obsidian の枠外用）
  ];
}
