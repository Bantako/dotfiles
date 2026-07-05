{ pkgs, ... }:

let
  feishinWithSecretStore = pkgs.symlinkJoin {
    name = "feishin-basic-text";
    paths = [ pkgs.feishin ];
    nativeBuildInputs = [ pkgs.makeWrapper ];
    postBuild = ''
      rm "$out/bin/feishin"
      makeWrapper ${pkgs.feishin}/bin/feishin "$out/bin/feishin" \
        --add-flags "--password-store=basic_text"
      rm "$out/share/applications/feishin.desktop"
      cp ${pkgs.feishin}/share/applications/feishin.desktop "$out/share/applications/feishin.desktop"
      substituteInPlace "$out/share/applications/feishin.desktop" \
        --replace-fail "Exec=feishin %u" "Exec=$out/bin/feishin %u"
    '';
  };
in
{
  # Spotify TUI
  programs.ncspot.enable = true;

  # OBS
  programs.obs-studio.enable = true;

  home.packages = with pkgs; [
    # デスクトップ基盤
    alacritty # フォールバックターミナル (ghostty障害時)
    fuzzel # アプリランチャー
    nemo # ファイルマネージャー
    xwayland-satellite # XWayland統合

    # Wayland ユーティリティ
    satty # スクショ加筆ツール（grim | satty でパイプ）
    grim # Wayland スクリーンショット取得
    slurp # 範囲選択（grim と組み合わせ）
    hyprpicker # カラーピッカー（HEX を wl-copy）

    # エンタメ・コミュニケーション
    discord-ptb
    (
      (prismlauncher.override {
        # GUI 版 openjdk は GTK3 を直接 NEEDED に持ち、JVM 起動時に libwayland-egl.so.1 を
        # プリロードする。これが Mesa の EGL Wayland platform 初期化と衝突して
        # eglGetPlatformDisplay が EGL_BAD_PARAMETER で失敗する。headless 版は GTK3 を含まない
        jdks = with pkgs; [
          jdk21_headless
          jdk17_headless
          jdk8_headless
        ];
      }).overrideAttrs
      (old: {
        qtWrapperArgs = (old.qtWrapperArgs or [ ]) ++ [
          "--unset DISPLAY"
          "--set GLFW_PLATFORM wayland"
          # LWJGL 同梱の GLFW を nixpkgs の Wayland 対応 GLFW に差し替え（dlsym で
          # eglGetPlatformDisplayEXT が取れない問題を回避）。PrismLauncher は
          # JAVA_TOOL_OPTIONS を strip するため Java 9+ の JDK_JAVA_OPTIONS を使う
          "--set JDK_JAVA_OPTIONS -Dorg.lwjgl.glfw.libname=${pkgs.glfw3-minecraft}/lib/libglfw.so"
        ];
      })
    ) # Minecraft: headless JDK + Wayland GLFW で起動
    feishinWithSecretStore # Navidrome / Jellyfin クライアント（ElectronのSecret Service判定を固定）
    slack
    spotify

    # メディア・ノート
    android-studio
    calibre # 電子書籍管理
    obsidian # ノート

    # ゲーミング
    mangohud # FPS/温度/CPU使用率オーバーレイ
    protonup-qt # GE-Proton等カスタムProton導入GUI
    protontricks # Proton prefixにwinetricksを当てる

    # ファイル交換
    localsend # LAN内アドホックファイル転送（AirDrop代替、スマホ⇔PC）
    jocalsend # LocalSend CLI（端末からファイルを投げる用）

    # その他
    featherpad # 汎用GUIテキストエディタ（コード=nvim、ノート=Obsidian の枠外用）
  ];
}
