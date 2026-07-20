{ pkgs, config, ... }:
let
  raindrop-to-daily = pkgs.writeShellScriptBin "raindrop-to-daily" ''
    exec ${pkgs.python3}/bin/python3 \
      ${config.home.homeDirectory}/.dotfiles/home/modules/cli/scripts/raindrop-to-daily.py \
      "$@"
  '';
  gitadora-tool = pkgs.writeShellScriptBin "gitadora-tool" ''
    exec ${pkgs.python3.withPackages (p: [ p.pyside6 ])}/bin/python3 \
      ${config.home.homeDirectory}/Projects/gitadora-wiki/tool/main.py \
      "$@"
  '';
  taggerRoot = "${config.home.homeDirectory}/Projects/szurubooru-tagger";
  booru-import = pkgs.writeShellScriptBin "booru-import" ''
    exec ${pkgs.python3}/bin/python3 ${taggerRoot}/szurubooru_import.py "$@"
  '';
  booru-fetch = pkgs.writeShellScriptBin "booru-fetch" ''
    set -euo pipefail

    staging_root="''${BOORU_STAGING_DIR:-$HOME/Pictures/booru-staging}"
    runtime_dir="''${XDG_RUNTIME_DIR:?XDG_RUNTIME_DIR is required}/gallery-dl"
    config_file="$runtime_dir/config.json"
    gelbooru_api_key="/run/secrets/gelbooru-api-key"
    gelbooru_user_id="/run/secrets/gelbooru-user-id"
    simulate=0
    urls=()

    while (($# > 0)); do
      case "$1" in
        --help|-h)
          printf '%s\n' \
            'Usage: booru-fetch [--simulate] URL [URL ...]' \
            '  Download explicit Pixiv/Gelbooru URLs and import them into Szurubooru.' \
            '  Use --simulate for download-only staging without API writes.'
          exit 0
          ;;
        --simulate|-s)
          simulate=1
          shift
          ;;
        --)
          shift
          urls+=("$@")
          break
          ;;
        -* )
          printf 'booru-fetch: unknown option: %s\n' "$1" >&2
          exit 2
          ;;
        *)
          urls+=("$1")
          shift
          ;;
      esac
    done

    if (( ''${#urls[@]} == 0 )); then
      printf '%s\n' 'booru-fetch: at least one URL is required' >&2
      exit 2
    fi

    timestamp="$(${pkgs.coreutils}/bin/date +%Y%m%d-%H%M%S)"
    run_dir="$staging_root/$timestamp"
    test -r "$gelbooru_api_key"
    test -r "$gelbooru_user_id"
    ${pkgs.coreutils}/bin/mkdir -p "$run_dir" "$runtime_dir"
    ${pkgs.coreutils}/bin/chmod 700 "$runtime_dir"
    umask 077
    ${pkgs.jq}/bin/jq -n \
      --rawfile api_key "$gelbooru_api_key" \
      --rawfile user_id "$gelbooru_user_id" \
      '{ extractor: { gelbooru: { "api-key": ($api_key | rtrimstr("\n")), "user-id": ($user_id | rtrimstr("\n")) } } }' \
      > "$config_file"
    ${pkgs.coreutils}/bin/chmod 600 "$config_file"
    printf '%s\n' "''${urls[@]}" > "$run_dir/SOURCE_URLS.txt"
    printf '%s\n' \
      'Automatic Szurubooru import is attempted after staging:' \
      'https://ser7.taild4ba88.ts.net:8446/' \
      'Keep SOURCE_URLS.txt with the staging item for source attribution.' \
      'This directory remains as a retryable import record.' \
      > "$run_dir/NEXT.txt"

    args=(
      --no-input
      --config "$config_file"
      --directory "$run_dir"
      --download-archive "$staging_root/.download-archive.txt"
      --error-file "$run_dir/errors.txt"
      --write-metadata
      --write-info-json
      --write-tags
    )
    if ((simulate)); then
      args+=(--simulate)
    fi

    ${pkgs.gallery-dl}/bin/gallery-dl "''${args[@]}" "''${urls[@]}"

    file_count="$(${pkgs.findutils}/bin/find "$run_dir" -type f \( \
      -iname '*.avif' -o -iname '*.gif' -o -iname '*.jpeg' -o -iname '*.jpg' \
      -o -iname '*.png' -o -iname '*.webp' \) -print | \
      ${pkgs.coreutils}/bin/wc -l)"
    printf 'staging_dir=%s\nfiles=%s\n' "$run_dir" "$file_count"
    if (( ! simulate )); then
      policy="''${BOORU_TAG_POLICY:-${taggerRoot}/tag-policy.json}"
      report="${taggerRoot}/reports/$timestamp-triage.json"
      ${pkgs.python3}/bin/python3 ${taggerRoot}/szurubooru_tagger.py scan \
        "$run_dir" --policy "$policy" --output "$report"
      ${booru-import}/bin/booru-import --username Bantako "$report" --apply
    fi
  '';
in
{
  xdg.configFile."ov/config.yaml".source = ./ov.yaml;
  xdg.configFile."yt-dlp/config".text = ''
    --cookies-from-browser "firefox:/home/morikawa/.config/zen/y6m6mt88.Default Profile"
  '';

  home.packages = with pkgs; [
    raindrop-to-daily
    gitadora-tool
    # 基本CLIツール
    uutils-coreutils-noprefix # GNU coreutils の Rust 代替（同名コマンドで上書き）
    bottom
    eza
    fzf
    ripgrep
    zoxide
    jq
    jless # JSON/YAML を navigate-first で歩く TUI

    # ターミナルツール群
    fio # ディスクI/Oベンチマーク
    gh # GitHub CLI
    ov # ページャー（yaziのbat連携）
    python3 # Pythonインタープリター
    nodejs_22 # Node.js（npx経由のMCPサーバー用）
    unzip # ZIP展開
    uv # Pythonパッケージマネージャー
    ouch # 統合アーカイブツール（tar/zip/zst等を統一コマンドで）
    tealdeer # tldr：manの代わりに使い方例を即表示
    visidata # CSV/JSON/TSVをTUIで探索・編集
    glow # ターミナルでMarkdownをレンダリング
    yt-dlp # YouTube等の動画ダウンロード
    ytfzf # YouTube TUI検索 → mpv 再生
    imagemagick # 画像変換・リサイズ・バッチ処理
    ffmpeg # 動画・音声変換

    # 補完エンジン
    carapace # 500+ コマンドの引数補完ブリッジ（sheldon 経由で fzf-tab より前に init）
    fclones # 重複ファイル検出・削除（Rust 製、~/Pictures 等の整理用）

    # Rust CLI 追加
    lazydocker # Docker コンテナ TUI (logs/restart/exec/prune)
    serpl # ripgrep+sed の対話 TUI（複数ファイル横断 find&replace）
    fd # find の Rust 代替
    sd # sed の Rust 代替
    xh # httpie の Rust 版
    hyperfine # ベンチマーク
    numbat # 単位変換つき高精度計算機（bc の代替）

    # ドキュメント変換
    pandoc # MD↔HTML/PDF/docx 等の文書変換

    # メディア・メタデータ
    exiftool # EXIF/メタデータ管理
    gallery-dl # 画像ギャラリーサイトの一括ダウンロード
    booru-fetch # gallery-dl staging → 自動タグ付け・Szurubooru取込
    booru-import # 候補レポートのSzurubooru取込（既定はdry-run）

    # Nix 管理
    nix-tree # Nix store 依存ツリーを TUI 探検
    nix-output-monitor # nh ビルド進捗をリッチ表示
    nvd # switch 前後のパッケージ差分表示
    just # 再現したい運用手順・dry-run・監査の永続化
    comma # `nix run` 不要の即席パッケージ実行 (`, cowsay hi`)

    # モダン診断・調査 CLI
    dust # du のツリー型モダン版（概要把握）
    ncdu # du のインタラクティブ TUI（j/k で掘っていける）
    procs # ps のカラー・ツリー表示版
    hexyl # xxd の bat 風カラー hex ビューア
    dog # dig のカラー代替

    # ドキュメント・録画
    vhs # ターミナル操作を GIF/MP4 録画 (.tape DSL)

    # 観測性・監視
    amdgpu_top # AMD GPU 使用率・VRAM・温度を TUI で表示
    smartmontools # SSD/HDD の SMART 監視 (smartctl)
    lm_sensors # CPU/GPU/M.2 温度 (sensors コマンド)
    trash-cli # trash-put でゴミ箱送り (rm の安全版)
    playerctl # Spotify/mpv をスクリプト・キーから制御

    # Nix lint
    deadnix # 未使用バインディング検出
    statix # Nix アンチパターン lint (deadnix の相補)
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
