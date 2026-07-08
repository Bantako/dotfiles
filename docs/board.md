# dotfiles ボード

未対応項目を**領域別 → 依存関係 → 状態タグ**で整理した一枚目。

---

## 上位制約 (全項目で参照)

判断・順序付けの際に常に確認する:

- **pruning phase** (2026-05〜) — パッケージ追加抑制 + 削除候補出し
- **単一ホスト集約** — ser7 1 台運用、マルチホスト前提の予防的抽象化はしない
- **navigate-first** — yazi/fzf/zoxide が daily-driver の中心。テキスト操作系より移動系を優先
- **アプリ採用 4 軸** — vim / plugin-based / fast / minimal UI。揃えばフレームワーク不問
- **NAS 3 軸** — コンテンツ + 制御 + PKM。サービス提案時は軸への寄与を明示
- **ベンダースタンス** — Microsoft 不採用、Google 距離、Qt 推奨/GTK 警戒/Electron 警戒

---

## 凡例

状態タグ: `[次]`着手可 / `[ブロック]`依存未解消 / `[保留]`用途立証待ち / `[現状維持]`判断済の不採用 / `[完了]`実装済
依存関係: 「ブロッカー: X」「依存: Y」「関連: Z」を各項目に明示

---

## 領域 1: daily-driver (毎日触る TUI / shell)

最頻ツールへの拡張が体感改善度最大。`navigate-first` + `アプリ採用 4 軸` の中心領域。

### yazi 拡充 `[完了]`

**管理方法確定**: plugins は `home/modules/cli/yazi/plugins/` に実ファイルとして格納 → Nix store 経由で `~/.config/yazi/plugins` にリンク。`ya pkg add` は read-only のため使えない。追加は dotfiles にファイル配置 + `package.toml` 更新 + nhs。

- **`zoxide.yazi`**: 不要。bunny hops が代替、zoxide は shell 側で完結。
- **`Y` (削除)**: keymap にカスタムなし。`trash-cli` 既存なのでデフォルト `D` でゴミ箱送り可。

着手順:
1. ~~**`git.yazi` + `glow` opener + `compress.yazi`**~~ — ✓ 完了
2. ~~**`restore.yazi`**~~ — ✓ 完了（`R` キー、freedesktop Trash から直接復元）
3. ~~**`mediainfo.yazi` + `mediainfo` パッケージ**~~ — ✓ 完了（video/audio プレビューに表示）
4. ~~**`pdf.yazi` / `cbz.yazi` プレビュー**~~ — ✓ 完了（pdftoppm + bsdtar + imagemagick、CBZ/CBR 両対応）

### jless `[完了]`

JSON/YAML を navigate-first で歩く。`tools.nix` に追加済。

### aerc / newsboat 評価 `[保留]`

TUI メーラー / RSS。4 軸完全 fit だが**読書フロー変更**を伴う重い候補。
**立証条件**: aerc は Thunderbird 疲れ等の動機 / newsboat は RSS 習慣復活。現状なし。
関連: [[FreshRSS + newsboat]] (newsboat 採用時の NAS サーバー側)

---

## 領域 2: NAS 3軸 (コンテンツ / 制御 / PKM)

### 制御軸

#### Homepage (ダッシュボード) `[完了]`

yaml 設定の minimal UI ダッシュボード。port 3001。
コンテナ状態（docker.yaml + server/container 指定）・システム情報（CPU/RAM/disk）ウィジェット有効。
全 NAS サービスのリンクを一元化。

**dashboard 比較（2026-05 決定）**: Homepage 確定。理由は「モダンさ」ではなく **宣言的（yaml only / DB なし / web 編集 UI なし）= config-as-code** で思想合致。
- **Homarr 不採用** — web ドラッグ&ドロップ + DB の可変状態モデルは「設定はファイルで宣言・状態を持たない」志向と逆。人気だが後退。
- **Glance** — さらに軽量 yaml だが強みが service 統計より RSS/市況等の情報フィード。用途違い → 将来 personal start page / PKM フィード用の**補完候補**（置換ではない）。

**ウィジェット拡充 `[完了]`**: Immich / Paperless / Navidrome / Calibre-web / ntfy / Stash widget 有効。Google Calendar・天気（openmeteo）・CPU温度・ブックマーク・glances・RSS（yazi/niri/lazygit/ghostty releases）・stocks（Finnhub: AAPL/NVDA/MSFT/SONY）追加済み。Jellyfin は API キー取得後 `.env` に追記するだけ。homepage config は `nas-git` で `~/services` 管理。

#### NAS ディレクトリ整理 (`~/data` / `~/services`) `[完了]`

- reorg 後パス検証済み（compose volume mount・Homepage 参照問題なし）
- `~/services` を git monorepo 化（allowlist `.gitignore`、`nas-git` 関数で ser7 から操作）
- compose + homepage/config/*.yaml を管理対象に追加済み

#### lazydocker (コンテナ運用 TUI) `[完了]`

`lzd` エイリアス（`DOCKER_HOST=ssh://nas lazydocker`）で NAS コンテナを TUI 管理。ssh 鍵認証済み。

#### Backblaze B2 バックアップ (restic) `[完了]`

NAS 全体の off-site バックアップ。restic + B2 の NAS コンテナ構成。

**構成**: `~/services/backup/` に compose.yaml + scripts/。alpine コンテナが毎朝 3 時に実行。
**対象**: photos/immich・music・documents・paperless・projects・backup/settings・Immich PostgreSQL dump
**ステータス表示**: darkhttpd（port 8090）で status JSON 配信 → homepage customapi widget
**スナップショット保持**: 日次 7・週次 4・月次 6
**コスト**: ~$1.42/月（237GB）、上限 $10/月設定済み

**写真整理**: Takeout を immich-go `--include-unmatched` でインポート完了。MobileBackup / PhotoLibrary / Takeout を `archive/photos/` に移動。

#### borg Phase 2 — healthchecks heartbeat `[保留]`

Phase 1（OnFailure → noctalia 通知）は完了済み。Phase 2 は「**そもそも実行されてない**」を検知する逆向きの補完。
ser7 が off の日は失敗イベント自体が出ないため Phase 1 だけでは検知できない。
healthchecks.io（self-host or SaaS）へ `ExecStartPost` で heartbeat を送り、猶予時間内に届かなければアラート。
**立証条件**: 「バックアップが数日止まってた」という実害を経験したとき。現状は Phase 1 で十分な在宅率。

### コンテンツ軸

#### Navidrome (Subsonic 互換音楽サーバー) `[完了]`

ローカル所有音楽用。ncspot (Spotify) との役割分担。Subsonic API でクライアント生態系厚い。
NAS deploy: docker-compose、`~/Music:/music:ro`、port 4533。Web UI のみ運用。
TUI クライアントは用途立証後に追加する。
関連: yazi `mediainfo.yazi` (NAS 動画と並ぶメディア整理文脈)

### PKM軸

#### FreshRSS + newsboat `[現状維持]`

**Miniflux + iris-news で実質解決 (2026-06)**: NAS に Miniflux を導入し、iris-news（LLM によるフィード要約・日次ビルド + 週次購読レビュー、systemd timer）で読書フローが定着。FreshRSS/newsboat の出番はなくなった。
関連: [[aerc / newsboat 評価]]

#### Datasette + dogsheep `[現状維持]`

Personal Data Warehouse。atuin / GitHub / Paperless / Immich 等を SQLite 横断分析。
**不採用**: 方向性が違うと判断 (2026-05-26)。

---

## 領域 3: system 運用

### クロス OS キーバインド正規化 `[現状維持]`

xremap は evdev レベル（コンポジター以前）でキーを書き換えるため、ghostty フォーカス中の Ctrl↔Super スワップが Niri の `Ctrl+Shift+3/4/5` ショートカットを壊す。「アプリ側だけ制御」は xremap では原理的に不可能。完全な解決策は未発見のため現状維持。

---

## 領域 4: nvim

### H Mason 完全停止 + Nix LSP 完全管理 `[完了]`

**なぜ必要だったか**: LazyVim デフォルトで Mason が有効になっており、各 LSP/formatter を Mason がインストールしようとする。NixOS では Mason の pre-built バイナリが glibc/動的リンカ不整合で壊れるため、`nil_ls` と `rust_analyzer` 以外の LSP が壊れたまま放置されていた。また `neovim.extraPackages` と `home.packages` で重複インストールも発生していた。Nix 完全管理に統一することで再現性を確保。commit: `41846ab`

---

## 領域 5: 横断 — stylix `[完了]`

base16 Dracula で全アプリ統一済み（2026-05-30）。ghostty / GTK / fuzzel / bat / zathura / yazi / delta が stylix 管理に移行。commit: `6d8ec5e`

---

## 領域 6: AI エージェント運用 (hermes / herdr)

2026-06 に立ち上がった新領域。ser7 の hermes agent（Discord bot + WebUI + TUI）と herdr（エージェント多重化）が中心。詳細な経緯は `analysis-hermes-nas-2026-07-06.md` と `report-nas-pruning-2026-07-08.md` を参照。

### hermes 堅牢化・セキュリティ `[完了]` (2026-07-06〜08)

分析ドキュメント P1〜P17 を一気に消化。allowlist 有効化 / `~/.hermes` バックアップ + etckeeper 方式 git 管理 / WebUI loopback 化 + メモリ制限 / extras 削減 (-694MiB) / シークレット混入対応 + コミット前スキャンゲート / OnFailure→ntfy 障害通知（テンプレートユニット + 誤検知抑止）/ **クリティカル承認層**（down -v・volume rm・restic forget・b2 delete・DROP DATABASE は毎回人間承認、キャッシュ不可）。

### B2 キーの deleteFiles なし再発行 `[次]`

バックアップを構造的に append-only 化。wger インシデント (2026-07-08) で「エージェントのミスがバックアップに届く」リスクが実証済み。クリティカル承認層と対になる最後のピース。**人間の作業**（Backblaze コンソール）。

### リストア訓練 `[次]`

immich の pg_dump を実際に別 DB へ復元してみる。復元したことのないバックアップは存在確認ができていないのと同じ。

### VectorChord 移行 `[保留]`

immich DB (pgvecto-rs pg14) → VectorChord (pg15)。server を v2.7.5 に pin 済みで時限爆弾は停止中。手順ドラフトは `report-nas-pruning-2026-07-08.md` にあり。
**立証条件**: immich を新バージョンに上げたくなったとき。

### シークレット一本化 (SOPS → .env 生成) `[保留]`

ser7 の `~/.hermes/.env` 平文と SOPS の二体系解消。キーが増えるほど効く。
ブロッカー: なし（着手順の問題のみ）

### 自前パッチの upstream PR 化 `[保留]`

`hermes-safe-tmp-deletes.patch` (105行) + `hermes-critical-approval-gate.patch` (171行) を flake input に当て続けるのは更新ごとの衝突リスク。クリティカル承認層は汎用機能なので受け入れられる可能性あり。

### ユビキタス化: メモ→リマインドループ `[保留]`

スマホ音声入力 → Discord → hermes 構造化 → ntfy X-Delay で時間起動リマインド。入口（キャプチャ摩擦ゼロ）と出口（文脈起動デリバリー）はセットで作らないと閉じない。既存資産（Discord home channel / Todoist / khal / ntfy）だけで組める。着手時に ntfy トピックを alerts / reminders に分離すること。
**立証条件**: 時間起動ループを 1 往復通す動機が立ったとき。

---

## やらない / 現状維持判断

### simplification-scan で判定済 `[現状維持]`

- **P1-C apps.nix 解体** — openldap 削除後、CLI/GUI 2 ファイル分離で明確
- **P1-H claudeAliases 見直し** — alias 2個のみだが「AI 関連は AI フォルダ」原則優先
- **P2-α `nixos/hosts/ser7/` フラット化** — sops 再暗号化コスト > 単一ホストの利得
- **P2-β `commands.nix`/`portal.nix` を inline** — navigate-first 嗜好に 1 ファイル 1 サービス
- **P2-γ `home/modules/ai/` 整理** — LLM スタック流動的、安定するまで保留
- **`niri.nix` 休止中 keybind ブロック** — 残す (ユーザー判断)

### 構造的に却下

- **Dracula パレット抽出 (`lib/colors.nix`)** — stylix で一掃済み
- **`with pkgs;` 排除** — Nix idiomatic、可読性損なってない
- **`hosts/ser7/` 保持しながらの小規模リネーム** — 中途半端 (やるなら P2-α、やらないなら現状維持)
- **sheldon プラグインの Nix 化** — sheldon 順序制御 (carapace-init を fzf-tab 前) に依存、リスク > 得
- **`apps.nix` の Vivaldi/Zen 統廃合** — Zen 試し中、Vivaldi プライマリ。ブラウザ試行落ち着いてから

---

## 完了済 (sprint アーカイブ)

2026-05-19 sprint:

| 領域 | 内容 | commit |
|---|---|---|
| simplification P0 | 死コード / 死コメント / コメント密度調整 | 294c7f8, c71c4e0 |
| simplification P1 | vimiv 外出し / ghostty CSS 外出し / sheldon→zsh 統合 / zshrc 外出し / sops 共通属性化 / openldap overlay 削除 | 77b1002, 57b2da0, 5a2e952, 356f6a4 |
| borg Phase 1 | OnFailure → noctalia 通知 + linger=true | b61eac8 |
| NAS TUI | immich-browse + immich_token sops 化 | 95b0970, 39de173 |
| NAS ファイル管理 | Paperless-ngx 導入・既存ドキュメント取り込み | NAS deploy (2026-05-17) |
| NAS 制御 | ntfy 導入・borg postHook (成功通知) + OnFailure (失敗通知) | NAS deploy + backup.nix (2026-05-20) |

2026-05-27 sprint:

| 領域 | 内容 | commit |
|---|---|---|
| yazi拡充 | git.yazi / glow opener / compress.yazi / restore.yazi (`R`) / mediainfo.yazi (`mi`) | 3a06dd0, f4cc5eb, 7b8ba0a |
| daily-driver | jless 追加（JSON/YAML navigate-first） | （tools.nix）|
| NAS コンテンツ | Navidrome 導入・`~/Music` マウント・port 4533 | NAS deploy (2026-05-27) |
| nvim clean | 未使用 spec 5ファイル削除（example / dankcolors / nvim-tree / telescope / nvim-treesitter） | 79c6887 |
| NAS 制御 | Homepage 導入・port 3001・全サービスリンク＋コンテナ状態＋システム情報 | NAS deploy (2026-05-27) |

2026-05-30 sprint:

| 領域 | 内容 | commit |
|---|---|---|
| nvim | Mason 完全停止 + LSP を Nix 管理に統一 | 41846ab |
| 横断 | stylix で Dracula テーマ一元管理 | 6d8ec5e |

2026-06-01 sprint:

| 領域 | 内容 | commit |
|---|---|---|
| AI | aider / bonsai 削除、co2read PEP8 修正 | d781e9f |
| yazi | PDF / CBZ / CBR プレビュー (pdf.yazi / cbz.yazi、poppler-utils + bsdtar + imagemagick) | 90f3d75 |
| パッケージ | amdgpu_top 追加（GPU TUI 欠落補完） | 685aa56 |
| パッケージ | iftop / iotop-c 削除（btm で代替） | 2522aef |

2026-06-04 sprint:

| 領域 | 内容 | commit |
|---|---|---|
| NAS バックアップ | Backblaze B2 契約・restic コンテナ・毎日 3 時スケジュール・homepage widget | NAS deploy (2026-06-04) |
| NAS 写真整理 | Takeout を immich-go で完全インポート・archive/photos に移動 | NAS (2026-06-04) |

2026-06 (月次ロールアップ):

| 領域 | 内容 | commit |
|---|---|---|
| AI | hermes agent 立ち上げ (Discord bot / WebUI + Tailscale Serve / v0.17.0) | 436607a, b203156, 4eef626 他 |
| AI | herdr 導入（エージェント多重化、Claude Code 検出 + 自前パッチ） | 112e22b, 3fe0115 他 |
| AI | opencode 導入、ccusage 追加 | 40f5119, 7e4a1af |
| PKM | iris-news（LLM フィード要約、日次 timer + Miniflux 連携） | 5294a58, 7627b06 他 |
| desktop | localsend + jocalsend（LAN ファイル転送、port 53317） | 754243c, c5929aa |
| desktop | feishin 導入 + keyring 問題の根本解決（PAM 解錠 + gnome-libsecret） | 7490cac, fe862ee |
| desktop | vdirsyncer + khal（CalDAV 同期・CUI カレンダー）、Pavlok bedtime | 9b9498a, dd0717d |
| system | tailscale0 を NM 管理から除外（MagicDNS 破損修正）、Beszel agent | b70bf1a, 97c9837 |

2026-07-06〜08 sprint (hermes/NAS 集中改善):

| 領域 | 内容 | commit |
|---|---|---|
| AI 分析 | hermes / NAS 横断分析 (P1〜P17) → ほぼ全消化 | analysis-hermes-nas-2026-07-06.md |
| AI security | GATEWAY_ALLOW_ALL_USERS 削除・WebUI loopback 化・extras -694MiB | e3b01b4, b2ba29c, 93ac66c |
| AI backup | ~/.hermes → NAS 毎晩同期 + etckeeper 方式 git 管理 + シークレットスキャンゲート | 94cc5de, 8197832, 2789f35 |
| AI 監視 | OnFailure→ntfy 障害通知（テンプレートユニット化・配信バグ修正）+ NAS heartbeat | 4fbcc7d, 452631d, da3ea72 |
| AI guard | クリティカル承認層（破壊的動詞は毎回人間承認・キャッシュ不可） | de735d6 |
| NAS 監視 | monitor スタック新設（unhealthy/exited 検出 → nas-alerts、状態変化時のみ） | NAS deploy (2026-07-07) |
| NAS pruning | filebrowser / adguardhome / glances / wger 削除（**wger DB 喪失インシデント**あり） | report-nas-pruning-2026-07-08.md |
| NAS 再現性 | immich v2.7.5 / paperless 2.20.15 / miniflux 2.3.1 に pin（:latest 廃止） | 同上 |
