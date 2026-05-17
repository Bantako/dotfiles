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
    nodejs_22     # Node.js（npx経由のMCPサーバー用）
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
    hyperfine     # ベンチマーク

    # ドキュメント変換
    pandoc        # MD↔HTML/PDF/docx 等の文書変換

    # メディア・メタデータ
    exiftool      # EXIF/メタデータ管理
    gallery-dl    # 画像ギャラリーサイトの一括ダウンロード

    # Nix 管理
    nix-tree              # Nix store 依存ツリーを TUI 探検
    nix-output-monitor    # nh ビルド進捗をリッチ表示
    nvd                   # switch 前後のパッケージ差分表示
    comma                 # `nix run` 不要の即席パッケージ実行 (`, cowsay hi`)

    # モダン診断・調査 CLI
    dust          # du のツリー型モダン版（概要把握）
    ncdu          # du のインタラクティブ TUI（j/k で掘っていける）
    procs         # ps のカラー・ツリー表示版
    hexyl         # xxd の bat 風カラー hex ビューア
    dog           # dig のカラー代替

    # ドキュメント・録画
    vhs           # ターミナル操作を GIF/MP4 録画 (.tape DSL)

    # 観測性・監視
    smartmontools  # SSD/HDD の SMART 監視 (smartctl)
    lm_sensors     # CPU/GPU/M.2 温度 (sensors コマンド)
    iotop-c        # リアルタイム disk I/O 内訳
    iftop          # リアルタイム帯域モニター
    trash-cli      # trash-put でゴミ箱送り (rm の安全版)
    playerctl      # Spotify/mpv をスクリプト・キーから制御

    # Nix lint
    deadnix        # 未使用バインディング検出
    statix         # Nix アンチパターン lint (deadnix の相補)
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
