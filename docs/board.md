# dotfiles ボード

未対応項目を**領域別 → 依存関係 → 状態タグ**で整理した一枚目。
詳細・設計・履歴は各 plan ファイルへのリンクで参照する。

詳細リファレンス: [`improvement-plan.md`](./improvement-plan.md)
設計メモ: [`borg-notify-plan.md`](./borg-notify-plan.md) / [`simplification-scan.md`](./simplification-scan.md) / [`notes-from-mac.md`](./notes-from-mac.md)

---

## 上位制約 (全項目で参照)

判断・順序付けの際に常に確認する:

- **pruning phase** (2026-05〜) — パッケージ追加抑制 + 削除候補出し
- **単一ホスト集約** — ser7 1 台運用、マルチホスト前提の予防的抽象化はしない
- **stylix 着手前** — テーマ周りの個別ハードコードは触らない (一斉置換予定。本制約は stylix 着手で解除)
- **navigate-first** — yazi/fzf/zoxide が daily-driver の中心。テキスト操作系より移動系を優先
- **アプリ採用 4 軸** — vim / plugin-based / fast / minimal UI。揃えばフレームワーク不問
- **NAS 3 軸** — コンテンツ + 制御 + PKM。サービス提案時は軸への寄与を明示
- **ベンダースタンス** — Microsoft 不採用、Google 距離、Qt 推奨/GTK 警戒/Electron 警戒
- **Mac↔home 編集ルール** — improvement-plan.md は home 専用、board.md は両側 OK、topic doc は Mac で新規作成して home に引き渡し

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

詳細: [notes-from-mac.md §7](./notes-from-mac.md)

### jless `[完了]`

JSON/YAML を navigate-first で歩く。`tools.nix` に追加済。

### aerc / newsboat 評価 `[保留]`

TUI メーラー / RSS。4 軸完全 fit だが**読書フロー変更**を伴う重い候補。
**立証条件**: aerc は Thunderbird 疲れ等の動機 / newsboat は RSS 習慣復活。現状なし。
関連: [[FreshRSS + newsboat]] (newsboat 採用時の NAS サーバー側)
詳細: [notes-from-mac.md §8](./notes-from-mac.md)

---

## 領域 2: NAS 3軸 (コンテンツ / 制御 / PKM)

**依存グラフ**:
```
[ntfy 採用判断] ──┬──> ntfy 構築 ──┬──> borg Phase 2 (制御)
                  │                  │
                  │                  └──> Homepage 検討
                  │
                  └──> Navidrome ────> Homepage 着手 (ntfy + Navidrome 追加後が最大効用)
```

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

### コンテンツ軸

#### Navidrome (Subsonic 互換音楽サーバー) `[完了]`

ローカル所有音楽用。ncspot (Spotify) との役割分担。Subsonic API でクライアント生態系厚い。
NAS deploy: docker-compose、`~/Music:/music:ro`、port 4533。Web UI のみ運用。
TUI クライアントは用途立証後に追加する。
関連: yazi `mediainfo.yazi` (NAS 動画と並ぶメディア整理文脈)
詳細: [notes-from-mac.md §9](./notes-from-mac.md)

### PKM軸

#### FreshRSS + newsboat `[保留]`

NAS で FreshRSS、TUI 側で newsboat。フィード同期可。
**立証条件**: RSS を読む習慣 / 復活動機 (GitHub release 追跡 / ブログ巡回集約 / YouTube RSS) が立つこと。現状なし。
関連: [[aerc / newsboat 評価]]
詳細: [notes-from-mac.md §8](./notes-from-mac.md) + [§9](./notes-from-mac.md)

#### Datasette + dogsheep `[現状維持]`

Personal Data Warehouse。atuin / GitHub / Paperless / Immich 等を SQLite 横断分析。
**不採用**: 方向性が違うと判断 (2026-05-26)。
詳細: [notes-from-mac.md §4](./notes-from-mac.md)

---

## 領域 3: system 運用

### クロス OS キーバインド正規化 `[次]`（旧 xremap 保留 → 解ける見込み）

**目標**: Mac/Win/Linux で同一物理キーボード・同一操作。物理 Ctrl位置=アプリ修飾(Mac=Cmd) / 物理 Win位置=Unix Control に固定済み（Mac は Karabiner、QMK/VIA）。
**核心**: 物理 Ctrl は「ターミナル=Super相当 / GUI=Control相当」と文脈で出し分けが必要 → firmware では不可、compositor のアプリ検出付き remap が必須。
**更新**: 旧「未解決（Niri で xremap のアプリ検出不可）」は古い。**xremap が Niri ネイティブ対応（`NIRI_SOCKET`）** → `application.not`/`only` が効けば成立。
**構成**: QMK(物理Ctrl→Super / 物理Win→Control) + ghostty(Super=app修飾、設定済) + xremap-niri(`Super→Control` を `application.not: ghostty`) + Niri(Mod=Alt で無干渉)。
**唯一の実証**: niri feature は nix-flake で "implemented, not tested"。ser7 で `application.not`/`only` が Niri 上で実際に効くか実証（`NIRI_SOCKET` 込みで xremap を niri ビルドに）。通らなければ keyd 等へフォールバック。
**現 `xremap.nix`**: `application.only: ghostty` の全アプリ leak 旧構成。→ firmware 前提に変更 + niri ビルド + modmap を `Super→Control`/`application.not: ghostty` に書き換え。
詳細: [CLAUDE.md キーバインド方針](../CLAUDE.md) + [improvement-plan.md K](./improvement-plan.md)

---

## 領域 4: nvim

### H Mason 完全停止 + Nix LSP 完全管理 `[次]`

集中 1〜2h の大規模変更。`nix-mason.lua` 書き換え + LSP を Nix 管理に統一 + 既存 Mason データ削除。
**注意**: [[stylix]] 着手と並行はリスク (両方とも広範囲)。順序付けはどちらか片方ずつ。
詳細: [improvement-plan.md H](./improvement-plan.md)

---

## 領域 5: 横断 — stylix `[次/大]`

base16 テーマ全アプリ統一。**上位制約「stylix 着手前」を解除する着手**。

着手で一掃される項目:
- Dracula パレット重複 (vimiv / noctalia / ghostty / gtk に分散)
- やらないリスト の「Dracula パレット抽出 (`lib/colors.nix`)」が自動解消
- simplification-scan の「stylix 導入時に〜」記述が effective に

**注意**: [[H Mason]] と並行はリスク。stylix を先に出すと、その後の各モジュール小修正で Dracula 周り考えなくて済む利点あり。
詳細: [improvement-plan.md stylix](./improvement-plan.md)

---

## やらない / 現状維持判断

### simplification-scan で判定済 `[現状維持]`

- **P1-C apps.nix 解体** — openldap 削除後、CLI/GUI 2 ファイル分離で明確
- **P1-H claudeAliases 見直し** — alias 2個のみだが「AI 関連は AI フォルダ」原則優先
- **P2-α `nixos/hosts/ser7/` フラット化** — sops 再暗号化コスト > 単一ホストの利得
- **P2-β `commands.nix`/`portal.nix` を inline** — navigate-first 嗜好に 1 ファイル 1 サービス
- **P2-γ `home/modules/ai/` 整理** — LLM スタック流動的、安定するまで保留
- **`niri.nix` 休止中 keybind ブロック** — 残す (ユーザー判断)

詳細: [simplification-scan.md](./simplification-scan.md)

### 構造的に却下

- **Dracula パレット抽出 (`lib/colors.nix`)** — [[stylix]] で一掃される。二重作業
- **`with pkgs;` 排除** — Nix idiomatic、可読性損なってない
- **`hosts/ser7/` 保持しながらの小規模リネーム** — 中途半端 (やるなら P2-α、やらないなら現状維持)
- **sheldon プラグインの Nix 化** — sheldon 順序制御 (carapace-init を fzf-tab 前) に依存、リスク > 得
- **`apps.nix` の Vivaldi/Zen 統廃合** — Zen 試し中、Vivaldi プライマリ。ブラウザ試行落ち着いてから

---

## いま着手可能 (short list)

依存解消済 + 上位制約と整合済を体感改善度順:

| 順 | 項目 | 領域 | 備考 |
|---|---|---|---|
| ~~0~~ | ~~**yazi 拡充**~~ | daily-driver | ✓ 完了（git / glow / compress / restore / mediainfo）|
| ~~1~~ | ~~**jless 追加**~~ | daily-driver | ✓ 完了 |
| ~~2~~ | ~~**Navidrome**~~ | NAS コンテンツ | ✓ 完了（NAS docker-compose、port 4533） |
| ~~3~~ | ~~**Datasette Phase 0 試運転**~~ | NAS PKM | ✗ 不採用（方向性が違う） |
| ~~4~~ | ~~**reorg 後パス検証**~~ | NAS 制御 | ✓ 完了（compose volumes / Homepage 参照 — 全部新パス。borg は NAS 自体を対象外、構造的） |
| ~~5~~ | ~~**compose のローカル git**~~ | NAS 制御 | ✓ 完了（`~/services` を git 管理。docker 経由、`nas-git` 関数で操作） |
| ~~6~~ | ~~**lazydocker 接続**~~ | NAS 制御 | ✓ 完了（`lzd` エイリアス、`DOCKER_HOST=ssh://nas`） |

これらが終わった後の中規模 sprint 候補: **stylix** (Dracula 一掃) / **H Mason** (LSP 統一)。両者は並行せず順次。

---

## 完了済 (直近 sprint アーカイブ)

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
