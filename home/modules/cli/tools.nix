{pkgs, config, ...}:
let
  raindrop-to-daily = pkgs.writeShellScriptBin "raindrop-to-daily" ''
    exec ${pkgs.python3}/bin/python3 \
      ${config.home.homeDirectory}/.dotfiles/home/modules/cli/scripts/raindrop-to-daily.py \
      "$@"
  '';
in {
  xdg.configFile."ov/config.yaml".source = ./ov.yaml;

  home.packages = with pkgs; [
    raindrop-to-daily
    # 基本CLIツール
    bottom
    eza
    fzf
    httpie
    ripgrep
    zoxide
    jq

    # ターミナルツール群
    fio           # ディスクI/Oベンチマーク
    gh            # GitHub CLI
    ov            # ページャー（yaziのbat連携）
    python3       # Pythonインタープリター
    nodejs        # Node.js（npx経由のMCPサーバー用）
    unzip         # ZIP展開
    uv            # Pythonパッケージマネージャー
    ouch          # 統合アーカイブツール（tar/zip/zst等を統一コマンドで）
    tealdeer      # tldr：manの代わりに使い方例を即表示
    visidata      # CSV/JSON/TSVをTUIで探索・編集
    glow          # ターミナルでMarkdownをレンダリング
    yt-dlp        # YouTube等の動画ダウンロード
    imagemagick   # 画像変換・リサイズ・バッチ処理
    ffmpeg        # 動画・音声変換

    # Rust CLI 追加
    fd            # find の Rust 代替
    sd            # sed の Rust 代替
    xh            # httpie の Rust 版
    navi          # 対話型コマンドチートシート
    hyperfine     # ベンチマーク

    # ドキュメント変換
    pandoc        # MD↔HTML/PDF/docx 等の文書変換

    # メディア・メタデータ
    exiftool      # EXIF/メタデータ管理
    gallery-dl    # 画像ギャラリーサイトの一括ダウンロード
  ];

  programs.atuin = {
    enable = true;
    enableZshIntegration = true;
    settings = {
      filter_mode_shell_up_key_binding = "session"; # ↑キーはセッション内履歴
      style = "compact";
    };
  };
}
