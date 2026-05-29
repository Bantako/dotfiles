# Mac 側セッションからの観察メモ

Mac 側の Claude Code セッションで気づいた、`docs/improvement-plan.md` に反映すべき情報を集約するファイル。
plan 本体は home 側 (ser7) で編集する運用のため、Mac からは本ファイルにためて引き渡す。

home 側で plan に反映したセクションは本ファイルから削除すること。

---



## 4. Personal Data Warehouse / Datasette 導入検討

### コンセプト

Simon Willison が 2020 年に提唱した [Personal Data Warehouses](https://simonwillison.net/2020/Nov/14/personal-data-warehouses/)。
自分のデータが各サービスに散在している状態を、**ローカル SQLite に集約して横断分析**するアプローチ。

実装ツール群: **Datasette**（SQLite を Web UI/SQL/JSON API として公開） + **Dogsheep**（13 種の `<source>-to-sqlite` ingestion ツール群） + **sqlite-utils**（DB 操作 CLI）。

2026 年現在も活発（1.0a29 / 2026-05-12 リリース）。

### §1 NAS TUI 基盤との関係（重要）

**直交する別レイヤー** として整理する。混ぜない。

| レイヤー | 役割 | UI |
|---|---|---|
| §1: NAS TUI ランチャ群 (`paperless-browse` 等) | **操作** (取り出す・送る) | TUI (fzf) |
| §4: Personal Data Warehouse (Datasette) | **分析・検索** (集計・facet・SQL) | Web |

「Web UI 文化に違和感」は割り切る。SQL 分析や facet 検索は TUI には合わない。

### ser7 環境への当てはめ

既に Personal Data Warehouse の素材として極めて適している:

| データソース | 現状 | Datasette 化のしやすさ |
|---|---|---|
| **atuin** (shell history) | 既に SQLite (`~/.local/share/atuin/history.db`) | そのまま開ける、摩擦ゼロ |
| **paperless-ngx** | NAS 上、REST API あり | `paperless-browse` の発展形として `paperless-to-sqlite` |
| **Immich** | NAS 上、公式 API あり | メタデータ・タグ・場所抜き出し |
| **Obsidian vault** | ローカル Markdown 群 | frontmatter / リンクグラフを自前スクリプト化 |
| **GitHub 活動** | 公式 `github-to-sqlite` あり | gh トークン流用 |
| **raindrop bookmark** | 既に `raindrop-to-daily.py` で API 叩いてる | 流れの一部を SQLite 化 |
| **claude-code/aider セッション** | `~/.claude/projects/*.jsonl` | スクリプト自作。AI 利用分析が可能 |

### 既存資産との関係

- **`raindrop-to-daily.py` のような「→ Obsidian」フローと、「→ SQLite」フローを二系統持つ**ことになる。役割分離を最初に決める:
  - **Obsidian** = 思考・編集・文章（人間が手で触る）
  - **Datasette** = データ・履歴・自動収集分（読み取り中心）
- **atuin が既に「shell history の Personal Data Warehouse」として動いている**。Datasette を被せると集計クエリ・可視化が増える（`atuin search` の TUI と直交）

### Nix での導入手段

| パッケージ | 状態 |
|---|---|
| `datasette` | nixpkgs にあり |
| `sqlite-utils` | nixpkgs にあり |
| dogsheep 個別ツール | 多くは nixpkgs 外。`uv` 経由 or 公式 Docker |

ホスティング候補:
- ser7 ローカル (systemd ユーザーサービス、localhost:8081) — 普段使い向き
- NAS の compose に乗せる — Immich/Paperless と並列、外部からアクセス可

### 導入の段階案

**Phase 0: 試運転（30 分）**
```bash
nix shell nixpkgs#datasette nixpkgs#sqlite-utils
datasette ~/.local/share/atuin/history.db --port 8081
# → ブラウザで atuin history を SQL で叩く
```
触ってみて「実際に欲しい使い方か」を判断。違和感あれば撤退、面白ければ Phase 1。

**Phase 1: 常駐化**
- `home/modules/data-warehouse/datasette.nix` 新設（§1 と並列の章扱い）
- systemd ユーザーサービスで `~/data/*.db` を見る datasette を localhost:8081 で起動
- 最初は atuin DB の symlink だけで OK

**Phase 2: ingestion 第1弾**
- 楽な `github-to-sqlite` で starred/repos/commits を取り込み
- systemd timer で日次更新

**Phase 3: 自前 ingestion（§1 と統合）**
- `paperless-to-sqlite` を `home/modules/nas/paperless.nix` に同居
- `immich-to-sqlite`（メタデータのみ）
- 命名規約は §1 と合わせる: `<service>-to-sqlite`

**Phase 4: 統合検索**
- `dogsheep-beta` で全 DB 横串の faceted search

**Phase 5: クエリ蓄積**
- `metadata.yaml` に保存クエリ
- 例: 月別 commit 数、ドキュメント追加推移、写真撮影地マップ

### モジュール配置の選択肢

```
home/modules/data-warehouse/
├── datasette.nix          # 本体・systemd service
├── ingestion/             # 各 *-to-sqlite ジョブ
│   ├── github.nix
│   ├── paperless.nix      # ← §1 nas/paperless.nix と分離 or 同居 を決める
│   └── ...
└── README.md              # スキーマ管理メモ
```

§1 の `home/modules/nas/<service>.nix` と、§4 の `home/modules/data-warehouse/ingestion/<service>.nix` が
ともに `<service>` 名を持つことになる。**`nas/` は操作、`data-warehouse/ingestion/` は ingestion** という責務切り分けで二重所有しない形が綺麗。

### オープン項目

- [ ] **二系統 (Obsidian / Datasette) の責務分離を明文化**するか（Phase 0 後）
- [ ] ホスティング場所: ser7 ローカル vs NAS compose
- [ ] `raindrop-to-daily.py` を SQLite 経由に書き換えるか、両出力にするか
- [ ] dogsheep 個別ツールを `uv` 管理にするか、自前で書き直すか
  - 単純な REST API ラップなら自前の方が NixOS 流（外部依存少ない）
- [ ] §1 の NAS TUI ランチャと §4 の ingestion を**同ファイルに同居**するか**分離**するか
- [ ] 公開範囲: 完全ローカルのみ / Tailscale 経由で他端末から / さらに外部
- [ ] バックアップ対象に `~/data/*.db` を含めるか（borgbackup §1 と関連）

### 評価

ユーザー環境は **データ主権 + 自前ツール文化 + 既存 SQLite (atuin)** のすべてを揃えていて、Personal Data Warehouse コンセプトとの適合度は高い。
ただし「Web UI 中心」の文化と TUI 志向のミスマッチを割り切れるかが入口条件。

### PIM (Personal Information Management) 全体のフェーズ認識

Datasette 導入は Phase 4 の手段。全体像を以下に整理:

| フェーズ | 内容 | 現状 |
|---|---|---|
| **Phase 0** | データを能動的に管理する必要があると認知する | 大学生時代に完了 |
| Phase 1 | 既製品を試す | サ終リスク・タグ付け・エクスポート困難で学習済み |
| Phase 2 | 自分でホストする | 進行中（NAS + Immich + Paperless） |
| Phase 3 | ツールを組み合わせる | 進行中（TUI ランチャ群、`raindrop-to-daily`） |
| Phase 4 | データを横断する | 今ここ（本セクション） |
| Phase 5 | 自分の使い方を発明する | 既製ワークフローを超えた個人最適化 |

#### Phase 0 が一番忘れられがち（重要）

「データを管理することを能動的にやる必要がある」という**認知レイヤー**。
これが無いと Phase 1〜5 の全部が空転する。

含まれる前提:
- データは放っておくと散らばる（重力に逆らわないと秩序は維持されない）
- 「いつか整理する」は来ない（仕組みで自動化されないものはやらない）
- サ終リスクは現実（Evernote / Pocket / Wunderlist の蓄積）
- タグ付けは難しい（認知科学的な既知問題、完璧な分類体系は存在しない）
- エクスポート機能は信用できない（データロックインがビジネスモデルだった時代）
- 「ちょうどいいアプリ」を待つのは無意味（自分の使い方は他人と違う）
- データを持つこと自体に責任が伴う（バックアップ・再現性・継承性）

→ Datasette / Personal Data Warehouse のような上位概念は、Phase 0 を経た人にしか刺さらない。
本ファイル / `improvement-plan.md` 全体が Phase 0 認知を前提に成立している。

### 既製品評価のスタンス（Notion を例に）

「プロプライエタリ = 拒絶」という単純な立場は取らない。個別の良し悪しで判定する:

**Notion について**:
- ❌ 思想が合わない（all-in-one workspace / block-based / 視覚 UI 中心 / クラウドファースト）
- ✅ ただし**ツールとしての完成度は高い**
- ✅ **囲い込みが比較的緩い**（Markdown/CSV エクスポート、API 提供）
- ✅ **外部連携能力**は健全（API, webhook, integrations）

→ Phase 0 を通った後でも、Notion 自体は「**思想は合わないが品質は認める**」という温度感。「サ終リスクが低い + 出口が用意されている」という意味で他のプロプライエタリより**信用に値する**ほう。

このスタンスは「OSS でなければ全部ダメ」というイデオロギーではなく、**「ロックインの強さ」と「思想の合致度」を独立に評価する**という実利的判断を取っているということ。
他のツールを評価する時の基準として残しておく。

---

Phase 0 の試運転（30 分でできる）で実体に触ってから判断するのが正解。

---

## 5. 音ゲー譜面 wiki（Obsidian Bases + ffmpeg + NAS）

### 位置付け

Phase 5（既製ワークフローを超えた個人最適化）の具体例。
既存ピース（ffmpeg / mpv / yt-dlp / Obsidian / NAS）を組み合わせて、
**音ゲー譜面の練習ログ + 動画ライブラリ**を自前で構築する。

### なぜこの構成が筋がいいか

| 構成要素 | 役割 | 既導入 |
|---|---|---|
| `yt-dlp` | 動画取得 | ✅ |
| `ffmpeg` | 分割・速度変更・切り出し | ✅ |
| `mpv` | 再生（A-B ループ・速度変更） | ✅ |
| Obsidian | Markdown + frontmatter + リンク | ✅ |
| **Obsidian Bases** | frontmatter を DB ビューで横断 | ✅ (Obsidian 1.9+) |
| NAS | 動画ファイルの物理置き場 | ✅ |

→ ピースは揃っているので**合体させるだけ**の段階。

### Frontmatter スキーマ案

譜面 1 つ = ノート 1 ファイル。

```yaml
---
game: chunithm        # chunithm / maimai / sdvx / iidx 等
title: "曲名"
artist: "アーティスト"
difficulty: master    # easy / advanced / expert / master / ultima
level: 14.5
bpm: 174
length_seconds: 135
genre: orig
status: practicing    # untouched / practicing / cleared / aaa
best_score: 1008500
best_lamp: fc         # clear / fc / ap
first_played: 2026-03-12
last_played: 2026-05-15
weak_sections: ["1:20-1:35", "2:10-2:20"]
tags: [音ゲー/chunithm, lv14.5]
video_full: "video/chunithm-曲名-master-full.mp4"
videos_sections:
  - "video/chunithm-曲名-bar4-001.mp4"
  - "video/chunithm-曲名-bar4-002.mp4"
---

# 曲名 [MASTER 14.5]

## 苦手箇所
- 1:20〜 縦連が抜ける
- 2:10〜 トリル密度高い

## 練習履歴
- 2026-05-15: ベスト更新 1008500
- 2026-05-12: 初 FC
```

### ffmpeg パターン集

```bash
# 1) 一定時間分割
ffmpeg -i fullsong.mp4 -c copy -map 0 \
  -segment_time 30 -f segment -reset_timestamps 1 \
  song-section-%03d.mp4

# 2) タイムスタンプ指定切り出し
ffmpeg -i fullsong.mp4 -ss 00:00:00 -to 00:00:18 -c copy intro.mp4

# 3) スローモーション版（譜面読み練習用）
ffmpeg -i section.mp4 -filter:v "setpts=1.5*PTS" -filter:a "atempo=0.667" \
  section-x0.67.mp4

# 4) 苦手箇所ループ動画化
ffmpeg -stream_loop 5 -i hard-part.mp4 -c copy hard-part-x5.mp4

# 5) BPM 同期分割（4 小節単位）
# 4 小節秒数 = 60 / bpm * 4 * 4
# bpm=174 → 4小節 ≈ 5.517 秒
BARS=4; BPM=174
SEG=$(echo "scale=3; 60 / $BPM * 4 * $BARS" | bc)
ffmpeg -i fullsong.mp4 -c copy -map 0 \
  -segment_time "$SEG" -f segment \
  song-bar${BARS}-%03d.mp4
```

**(5) BPM 同期分割が肝**。譜面の論理単位（小節）と動画チャンクがズレない。

### ディレクトリ構造案

```
~/Obsidian/music-games/
├── _index.md                          # 全体 MOC
├── games/
│   ├── chunithm.md                    # ゲーム別 index
│   ├── maimai.md
│   └── sdvx.md
├── charts/
│   ├── chunithm-曲名-master.md         # 1 譜面 1 ファイル
│   └── ...
├── attachments/video/                  # NAS への mkOutOfStoreSymlink
│   ├── chunithm-曲名-master-full.mp4
│   └── chunithm-曲名-bar4-001.mp4
└── views/
    └── practicing.base                 # Obsidian Bases 定義
```

**動画本体は NAS**、vault からは symlink で繋ぐ（neovim 設定と同じ手法）。
vault サイズが膨張せず、git 同期も軽い。

### Obsidian Bases のビュー例

`views/practicing.base` イメージ:

```yaml
filters:
  and:
    - file.path.startsWith("charts/")
    - status == "practicing"
views:
  - type: table
    name: 練習中
    order:
      - title
      - game
      - level
      - bpm
      - last_played
      - best_score
    sort:
      - column: last_played
        direction: desc
  - type: table
    name: クリア済み
    filters:
      - status == "cleared"
```

ゲーム別、難易度別、最近触ったもの順、苦手リスト等を**1 つの DB のように扱える**。

### chart-import スクリプト案（§1 NAS TUI 規約に乗せる）

`home/modules/nas/rhythm.nix`（仮）に `writeShellScriptBin`:

```bash
chart-import <youtube-url> <game> <title> <difficulty> <bpm> [bars=4]
```

処理フロー:

1. `yt-dlp` で動画取得 → 一時 mp4
2. `ffmpeg` で BPM 同期分割（4 小節単位）
3. NAS の `/mnt/ugreen/music-games/<game>/` に配置
4. Obsidian vault に frontmatter 付き Markdown ノート生成
5. `attachments/video/` に NAS への symlink
6. 完了通知

§1 の命名規約に沿わせると:
- スクリプト名: `chart-import` / `chart-browse` / `chart-stats`
- ファイル: `home/modules/nas/rhythm.nix`
- env: `MUSIC_GAMES_NAS_PATH` 等を zsh `sessionVariables` で定義

### 統合関係

このプロジェクトは **§1 / §4 / §5 の交点**:

| セクション | 寄与 |
|---|---|
| §1 NAS TUI 基盤 | `chart-import` / `chart-browse` 等のスクリプト群が乗る |
| §4 Personal Data Warehouse | `charts/*.md` の frontmatter を sqlite-utils で取り込めば横断分析可能（成績推移・難易度別クリア率） |
| §5 譜面 wiki 本体 | Obsidian + Bases で日々の練習ログ |

### Plain Text 主義との整合性

| 項目 | 形式 | plain text |
|---|---|---|
| ノート本体 | Markdown | ✅ |
| メタデータ | YAML frontmatter | ✅ |
| Bases 定義 | YAML | ✅ |
| 動画 | mp4 | ⚠️（本質的にバイナリ、不可避） |
| 動画メタ | ffprobe で抽出可能 | ✅（メタ部分） |

動画以外は完全に plain text。データ移行コストは限りなくゼロ。

### オープン項目

- [ ] 対象ゲームの確定（chunithm / maimai / sdvx / iidx / その他）
- [ ] 動画ソース戦略（公式 PV / 達人プレイ / 自分のプレイ録画）
- [ ] BPM 自動検出ツール（aubio 等）を入れるか手入力で済ますか
- [ ] スコア入力の自動化 vs 手入力（ゲーム側 API があるか調査）
- [ ] vault 公開リスク（譜面動画の著作権、公開 vault には乗せない）
- [ ] §4 Datasette との統合タイミング（practice ログを SQL で分析）

### 完成像（妄想）

```bash
# 新譜面を追加
chart-import https://youtube.com/... chunithm "曲名" master 174

# 練習する
chart-browse                    # fzf で譜面選択 → mpv で再生
chart-browse --status practicing # 練習中のものだけ

# 統計
chart-stats                     # 月別練習時間・クリア推移
# → Datasette が起動して /charts ページにジャンプ（将来）
```

完全に**個人専用音ゲー OS**。世界で何人やってるか不明。日本語圏で公開してる人はほぼいなさそう。

---

## 6. jless 追加候補

### 動機

現状 JSON 系の装備が `jq` (テキスト操作) + `visidata` (CSV/TSV) のみで、**JSON だけ navigate-first 軸の対応ツールが空いてる**。
yazi / zoxide / fzf-tab / atuin / vimiv / zathura で「眼で歩く」をやってる横で、`gh api ... | less` の結果だけがプレーンテキストなのは不整合。

### jless の位置付け

- パイプ / ファイル両対応（`gh api ... | jless` も `jless data.json` も可）
- JSON / YAML 自動判別 → `sops -d secrets.yaml | jless` でも読める
- j/k で navigate、キーパス検索、型ハイライト
- 速い / ハイライト / オプション分かりやすい — 選定軸 3 つ全部 fit

### fx は外す

fx は「対話的に jq 式を組む」方向の TUI。目的が違う（jless = 読む / fx = 探る）。
**jq 式は AI に書かせている** ので、対話的な式組み立ては不要。fx は候補から外す。

### 二段運用の典型

```bash
jq '.results[]' raw.json | jless       # jq で絞る → jless で歩く
sops -d secrets.yaml | jless           # 秘密も TUI で navigate（一時表示のみ）
gh pr view 123 --json title,body,reviews | jless
```

`jq` の出力が長いときに従来 `less` だと構造が消える問題を解決する。
jq 抜きでも `gh api ... | jless` だけで生の API response を歩ける。

### pruning phase 中の追加是非

`project_pruning_phase` memory（2026-05〜 追加抑制）に逆らう追加だが、
- navigate-first 軸の**真の穴**を埋める（既存装備の論理的な続き）
- 単独パッケージで完結（依存なし）
- 1ヶ月使って定着しなければ削除する自己制御を前提
- improvement-plan の「ポリシー: モダン CLI 置換」枠に該当（既存標準ツールの上位互換 + 特殊用途版）

→ **pruning phase の例外として承認**。

### 追加場所

`home/modules/cli/tools.nix` の **「モダン診断・調査 CLI」セクション**（dust / ncdu / procs / hexyl / dog の隣）に：

```nix
jless         # JSON/YAML を TUI で navigate（jq の出力先・API response の閲覧）
```

### improvement-plan.md 完了済テーブルへの追記候補

```markdown
| **jless** | JSON/YAML TUI navigate（モダン CLI 置換ポリシー範疇、fx は AI で jq 書ける前提から不要） |
```

---

## 7. yazi プラグイン・opener 拡充候補

### 動機

`user_app_style_preference` の 4 軸（vim/plugin-based/fast/minimal UI）を完全に満たす yazi は最頻 TUI。**新規 TUI を追加するより、yazi 拡張で機能を吸収する方針**が memory 統合運用と整合する。

現状の yazi 配下：
- plugins: `bunny` / `chmod` / `mime-ext` / `smart-enter` / `smart-filter` / `system-clipboard`
- flavor: `dracula`
- opener: zathura / vimiv / mpv / bat+ov / ouch (extract のみ) / exif / xdg-open

→ **git 状態表示・圧縮対称・安全削除・markdown レンダ・メディア情報**が未カバー。

### 候補一覧

#### A. `git.yazi`（プラグインのみ、新規パッケージなし）

ファイルリスト横に git ステータス記号（M/A/?/!/✓ 等）を表示。
- dotfiles / projects 配下で yazi 開いた時に常時恩恵
- ranger の `--git-status` 相当
- minimal UI を壊さない

#### B. `glow` を opener に追加（パッケージ既存、config 追加のみ）

`glow` は `home/modules/cli/tools.nix` に**既存**。yazi の opener として markdown 用エントリを追加。

```toml
# yazi.toml [opener] セクション
show_md = [
  { run = 'glow -p "$@"', block = true, desc = 'View Markdown (glow)' }
]
```

```toml
# yazi.toml [open] prepend_rules に追加
{ mime = "text/markdown", use = ["show_md"] },
```

Obsidian ノートを yazi 経由で TUI レンダ表示できる動線が綺麗になる。

#### C. `compress.yazi`（プラグインのみ、新規パッケージなし）

選択中のファイルを ouch で圧縮するプラグイン。`ouch` は既存。
- 現状 opener に `extract` だけある（片肺）
- 圧縮側も yazi 内から呼べるようになる
- 対称性が取れる

#### D. `restore.yazi` + 既存 `trash-cli`（プラグインのみ、新規パッケージなし）

`trash-cli` は既に `home/modules/cli/tools.nix` にある。`restore.yazi` プラグインで yazi 内から復元 UI。

- 削除キーを `trash-put` 経由に置き換える設定が前提（yazi.toml で削除動作を再定義）
- ranger の `:trash` 文化を yazi に持ち込む

#### E. `mediainfo.yazi` + `mediainfo` パッケージ（**唯一の新規追加**）

動画・音声ファイルプレビューで codec / bitrate / duration / 解像度 を表示。
- 現状の opener `exif` は画像 EXIF のみ
- NAS の動画整理時、yazi 内で属性が見える
- mediainfo はパッケージ追加が必要

### pruning phase との整合

新規パッケージ追加は **`mediainfo` 1 つだけ**。残り 4 つは plugin/config 追加で済むので pruning 制約に**触れない**。

`mediainfo` についても：
- 用途明確（NAS の動画整理）
- ffmpeg 一族の枯れた CLI、ロックインなし
- yazi 内で活きるという具体使用文脈

→ 例外承認の閾値を超えてる。

### 推奨着手順

| 順 | 項目 | 内容 |
|---|---|---|
| 1 | `git.yazi` | プラグインインストール（最も恩恵大） |
| 2 | `glow` opener | yazi.toml に entry + mime rule 追加 |
| 3 | `compress.yazi` | プラグインインストール、`c` キーバインド |
| 4 | `restore.yazi` | プラグイン + 削除キー再定義 |
| 5 | `mediainfo.yazi` + `mediainfo` パッケージ | tools.nix に追加 + プラグイン |

1〜3 は同時に着手可能（パッケージ追加なし）。4 は削除動作変更があるので慎重に。5 は最後。

### improvement-plan.md 完了済テーブル候補

```markdown
| **yazi プラグイン拡充** | git/compress/restore/mediainfo の 4 プラグイン + glow opener + mediainfo pkg |
```

### 確認事項（家側で）

- `zoxide.yazi` 相当（`gz` で z jump）が bunny に統合されてるかどうか
- 現状の `Y`（削除）の実体（即 unlink か trash-put か）

---

## 8. TUI メーラー / RSS リーダー（評価候補メモ）

### 位置付け

即時導入候補ではなく、**用途が立った時に評価する候補**。`user_app_style_preference` の 4 軸（vim / plugin-based / fast / minimal UI）に完全 fit するため、yazi 民の自然な拡張先になりうる。

### 候補

#### `aerc`（メーラー）

- vim 風 TUI メールクライアント
- IMAP / JMAP / maildir / SMTP 対応
- Lua plugin、キーバインド完全カスタム
- `[ ]` でアカウント切替、`v` でビジュアル選択、`d` で削除 → yazi 文法と一致
- 4 軸完全 fit

**評価が立つ条件**:
- メールを TUI で読みたい動機が出る
  - Thunderbird / ブラウザのウェブメール疲れ
  - 複数アカウント横断を高速化したい
  - notmuch などのインデクサと組み合わせたい
- 現状そういう不満が出てない or 出ても許容範囲なら**保留で良い**

#### `newsboat`（RSS リーダー）

- vim 風 TUI RSS リーダー
- フィード grouping、`j/k` で読み進める
- マクロで外部ブラウザ起動、podcast 対応
- 4 軸完全 fit

**評価が立つ条件**:
- RSS を読む習慣 / 復活させる動機が立つ
  - GitHub release 追跡を自動化したい
  - ブログ巡回を集約したい
  - YouTube の RSS 機能で動画追跡したい（Vivaldi の代替）
- 現状 RSS を使ってないなら**そもそも候補に上らない**

### 共通注意

両方とも**「読書フロー」自体の変更**を伴う。パッケージ単体追加で済まず、メールサーバー設定 / フィード収集 / バックアップ方針まで波及する。

→ pruning phase の例外承認には**用途立証が前提**。「便利そう」だけでは入れない。

### 関連候補（同類、紹介止まり）

- `ncmpcpp` — MPD frontend、ローカル音楽を TUI で。ncspot（Spotify）と用途違い
- `iamb` — Matrix TUI クライアント（Matrix アカウント持ちなら）
- `weechat` — IRC / Matrix 兼用、古典で枯れてる

これらも 4 軸 fit だが**用途立証**が前提条件。

### improvement-plan.md 上の扱い

- 現時点では「**保留候補リスト**」に置く（完了済テーブルには入れない）
- 採用時は jless / yazi 拡充と同じく**pruning phase 例外承認**プロセスを通す

---

## 9. NAS 拡張候補（3 軸戦略）

### 戦略 framing（本人明言）

> コンテンツ + 制御 + PKM (ナレッジ) を育てていきたい

| 軸 | 既存装備 |
|---|---|
| コンテンツ | Jellyfin / Stash / LANraragi / Calibre / Immich |
| 制御 | borg / syncthing / tailscale / NixOS monitoring |
| PKM | Paperless / Obsidian (local) + Quartz → Cloudflare Pages（**公開 Wiki 確立済み**、SilverBullet 等の Wiki 系は不要） |

### 承認候補

#### A. `ntfy`（制御軸）

**通知ハブ**。self-host な push 通知サービス。
- Web/モバイル/CLI から POST するだけで購読端末に push
- borg-notify-plan の自然な延長：noctalia 通知に加えて **ntfy 経由でスマホにも push**
- healthchecks.io の self-host 代替にもなり得る（heartbeat 失敗時に ntfy 通知）
- 配置: Ugreen NAS、Docker / Podman で立てる
- borg postHook で `curl -d "completed" https://ntfy.local/borg` の 1 行で連携

**統合の自然さ**:
- 既存 borg-notify-plan の "C. healthchecks 系" を ntfy 自前 push に置換可
- 計画ファイル `docs/borg-notify-plan.md` の **Phase 2 を ntfy ベースで書き直す価値**あり

#### B. `Navidrome`（コンテンツ軸）

**Subsonic API 互換の音楽サーバー**。
- ローカル音楽（FLAC/MP3）を NAS から streaming
- Subsonic API なので**クライアント選択肢が広い**：
  - **TUI**: `sublime-music-cli`、`stmps`、`supersonic`
  - **GUI**: `feishin`（4 軸 fit、Electron だが軽量）、`tauon`
  - **モバイル**: Symfonium / DSub / play:Sub 等
- ncspot との役割分担：**ncspot = Spotify、Navidrome = ローカル所有音楽**

**コンテンツ軸での位置**:
- 「自分の音源を Spotify に依存せず聴く」枠
- Jellyfin の音楽機能と被るが、Subsonic API 連携でクライアント生態系が圧倒的に厚い

#### C. `Homepage`（制御軸）

**サービスダッシュボード**（yaml 設定、minimal UI、4 軸寄り）。
- ブックマーク + サービス生存ステータス + 簡易メトリクスを 1 画面に
- yaml で全部宣言、Web UI で編集する設定 UI を持たない（**minimal UI / Niri 民の感性と整合**）
- 既存サービスへの導線：Jellyfin / Immich / Paperless / Stash / LANraragi / Calibre / Navidrome / ntfy 全部を 1 ページに

**配置タイミング**:
- サービスが 7 個以上になった今が**ちょうど価値が立つ**タイミング
- ntfy / Navidrome 追加後だと**10 個近く**になるのでなおさら有用

### 保留候補

#### D. `FreshRSS` + `newsboat`（PKM 軸、保留）

- §8 で書いた `newsboat` のサーバー側として `FreshRSS` を NAS で立てる
- newsboat は FreshRSS の API 経由でフィード同期可能 → **スマホからも同じフィード読める**
- 候補としてメモ、**用途立証は保留**（RSS 習慣が復活するかどうか）

### 共通注意

- 全部 self-hosted、**Microsoft / Google 距離スタンスと整合**
- パッケージ追加ではなく NAS 上の service なので **pruning phase の package 制約には触れない**（ただし service の安易な追加も歓迎ではないので、軸への寄与を明示してから入れる）
- 配置・運用形態（Docker / Podman / NixOS module）は家側で決める

### 推奨着手順

| 順 | 項目 | 理由 |
|---|---|---|
| 1 | **ntfy** | borg-notify-plan の延長で動機明確、計画文書既存 |
| 2 | **Navidrome** | コンテンツ軸最大の穴、独立サービスで影響範囲狭い |
| 3 | **Homepage** | 上 2 つ追加後に「目次」として最大効用 |

### improvement-plan.md への追記候補

```markdown
## NAS 育成（3 軸戦略）

### 軸定義
- コンテンツ + 制御 + PKM の 3 軸で育成

### 着手候補
| サービス | 軸 | 状態 |
|---|---|---|
| ntfy | 制御 | 着手予定（borg-notify-plan Phase 2 と統合） |
| Navidrome | コンテンツ | 着手予定 |
| Homepage | 制御 | 着手予定 |
| FreshRSS + newsboat | PKM | 保留（用途立証待ち） |
```

---

## 10. NAS reorg 後始末 + lazydocker（ser7/NAS 側で実行）

Homepage 導入と `~/data` / `~/services` へのディレクトリ整理が完了した直後の handoff。
**Mac からは NAS（`192.168.0.222`）も ser7 も触れない**ため、以下は ser7 にログインして実行する。
結果は board の該当項目にチェックを入れて記録する。

### ① reorg 後のパス検証（最優先・新ツールより先）

ディレクトリを移動したので、旧パスを掴んだまま静かに壊れている箇所を潰す。

- **borg バックアップ対象**: `backup.nix` の include が `~/data` / `~/services` を指しているか。
  旧パスのままだと移動したデータがバックアップから外れる（ntfy 成功通知が来ても中身が空はあり得る）。
  ```sh
  # ser7 側
  grep -rn 'paths\|include\|data\|services' /home/morikawa/.dotfiles/nixos/**/backup.nix
  # 直近バックアップに新パスが含まれるか
  borg list <repo>::<latest-archive> | grep -E 'data|services' | head
  ```
- **compose の volume bind mount**: NAS 上の各 compose（immich / paperless / navidrome / homepage）の
  `volumes:` が旧パスを指していないか。再 up で旧パスを掴み直す可能性。
  ```sh
  # NAS 側
  grep -rn 'volumes\|/data\|/services' ~/services/*/docker-compose.y*ml
  docker inspect <container> --format '{{json .Mounts}}' | jq   # 実マウント確認
  ```
- **Homepage の参照**: `docker.yaml` の server/container 指定・bookmarks リンクが移動の影響を受けていないか
  （port は変わっていないはずなので主に表示崩れ確認）。

### ② compose のローカル git 管理（制御軸の地力）

`~/services` の compose が version 管理されていなければ「前いじったの何で?」の履歴も revert も効かない。
ただし**編集は稀 + NAS は ser7 に常時マウント済み**なので、cross-machine の git パイプライン
（bare repo / post-receive フック / 外部 remote）は過剰。**NAS でローカル git を持つだけで十分**。

**構成（2026-05 詳細化）**:
- **monorepo + 複数 compose** — `~/services` をリポジトリルートに、各サービスは `~/services/<svc>/compose.yaml` の別 compose のまま。
  **git の粒度とコンテナの起動範囲は独立**: 1 サービスだけ変更したら `cd ~/services/<svc> && docker compose up -d` で
  そのコンテナだけ再作成（他は無停止）。「全部入り 1 compose」にしない限り全停止は起きない。`git commit` 自体はコンテナに無関与。
- **allowlist な `.gitignore`** — blocklist（`.env` を除外）だと除外し忘れで secrets/データが混入する。
  **全無視 → compose と必要設定だけ明示許可**にすれば、`.env` 実体やデータは許可しない限り原理的に入らない。

確認:
```sh
git -C ~/services rev-parse --is-inside-work-tree 2>/dev/null || echo "未管理"
```

未管理なら、既存の `~/services` でそのまま git 化する（**やり直しゼロ**・現状がそのままスナップされる）:
```sh
cd ~/services
git config --local core.fileMode false   # マウント越し時 CIFS のパーミッション固定で誤差分が出るのを抑制
cat > .gitignore <<'EOF'
# 全部無視
*
# ディレクトリは無視解除（配下に降りるため。これが無いと走査しない）
!*/
!.gitignore
# 追跡したいものだけ許可
!**/compose.yaml
!**/compose.yml
!**/docker-compose.yml
!**/docker-compose.yaml
# サービスごとに再現に要る設定があれば個別追加（実体 .env は足さない）
# !**/.env.example
# !**/*.conf
EOF
git init && git add -A
git status   # ← commit 前に必ず目視: yml と必要設定だけが staged か（DB 実体/秘密が混ざってないか）
git commit -m "init: NAS compose スタック現状スナップ"
```

運用フロー（remote もフックも 2 個目の clone も無し）:
- **編集 + git は ser7 のマウント越しに直接** — エージェント（Claude Code）/ nvim が native にファイルを触れて git も叩ける＝
  **SSH レス**。ssh 越しだと毎回 `ssh nas 'git ...'` でファイルツールが使えず面倒なため、こちらを第一選択に。
- **遅さ対策（必要時のみ）** — マウント越し git は `.git` の小ファイル書き込みが SMB 越しで遅い。compose 数ファイルなら実用範囲だが、
  気になれば `git init --separate-git-dir ~/repos/nas-services.git ~/services` で **worktree は NAS / `.git` は ser7 ローカル**に分離。
- **コンテナ再起動だけ NAS 側** — `docker compose up -d` は NAS で（or ssh）。分担: git=ser7 マウント越し、起動=NAS。
- **off-NAS 保全**: ①で borg が `~/services` を include していれば `.git` ごとバックアップされる → 外部 remote 不要。
  include していなければ borg 側に足すのが筋（GitHub 経由より素直）。

却下した重い案（編集頻度・マウント前提に対し過剰）:
- ~~bare repo on NAS + post-receive で push-to-deploy~~ — 編集が頻繁で ser7 環境で書きたい時のための仕組み。今は不要。
- ~~外部 remote（GitHub）経由で NAS が pull~~ — 外部依存 + pull トリガが増えるだけ。
- ~~dotfiles に取り込み~~ — NAS は NixOS でなく nix deploy できない。レイヤを混ぜない（[[project_single_host_policy]]）。

### ③ lazydocker 接続設定

`tools.nix` に `lazydocker` 追加済（Mac 編集）。ser7 で nhs 後、NAS の docker を指す。

- **思考非中断主義に最も合う形**: ser7 ローカルから `DOCKER_HOST=ssh://<user>@192.168.0.222 lazydocker`。
  ターミナルから手を離さず NAS コンテナの logs/restart/exec/prune ができる。
- **前提（ser7 で要確認）**:
  - ser7 → NAS の ssh が鍵認証で通ること（`ssh <user>@192.168.0.222 docker ps`）。
    Ugreen NAS の ssh ユーザー名は immich/paperless が HTTP API しか使っていないため dotfiles 上に情報なし → **要確認**。
  - リモート（NAS）側に docker CLI があること（lazydocker は ssh 越しに `docker system dial-stdio` を叩く）。
- **設定方法（どちらか）**:
  ```sh
  # 簡易: alias（zshrc.sh）
  alias lzd='DOCKER_HOST=ssh://<user>@192.168.0.222 lazydocker'
  # or docker context（docker CLI も入れる場合）
  docker context create nas --docker host=ssh://<user>@192.168.0.222
  DOCKER_CONTEXT=nas lazydocker
  ```
- ssh が通らない / Ugreen が docker CLI を載せていない場合のフォールバック:
  `ssh nas` してから NAS 上で lazydocker（NAS に別途インストールが必要なため一手増える。非推奨）。

### ④ Homepage ウィジェット拡充（ゴリ盛り → 必要なものだけ残す）

方針: **一旦取れる widget を全部盛って、実際に視線が行くものだけ残す**。ダッシュボードの中身は
yaml 編集だけで足し引き自由（Homepage は yaml をホットリロード）なので、最小から積むより
「全部出して観察 → 削る」が glance 先の判断に向く。ここは git パイプラインのような
「作ること自体がコスト」の話とは別で、ゴリ盛りが合理的。

**前提**: widget の API キーは Homepage（NAS）側の env に置き `{{HOMEPAGE_VAR_*}}` で参照。
これは §10 ② で gitignore する `.env` に入れる（ser7 の sops とは別管理）。port は各 compose に合わせる。

ウィジェット可否（2026-05 時点、gethomepage.dev で確認）:
- **あり**: immich / paperlessngx / jellyfin / navidrome / stash / calibreweb / ntfy
- **無し**: LANraragi → リンクカードのみ
- 複数 widget（ntfy / stash 等）は **fields を何個書いても先頭 4 個しか表示されない** → 並び順が効く（これも「盛って削る」レバー）

#### services.yaml（3 軸でグループ化・全 widget 盛り）

```yaml
- コンテンツ:
    - Immich:
        href: http://192.168.0.222:2283
        icon: immich.png
        server: my-docker      # docker.yaml の server 名。コンテナ状態もカードに出る
        container: immich_server
        widget:
          type: immich
          url: http://192.168.0.222:2283
          key: "{{HOMEPAGE_VAR_IMMICH_KEY}}"
          version: 2            # Immich v1.118+ は 2。key は server.statistics 権限必須
          fields: ["photos", "videos", "storage", "users"]
    - Jellyfin:
        href: http://192.168.0.222:<jellyfin-port>
        icon: jellyfin.png
        widget:
          type: jellyfin
          url: http://192.168.0.222:<jellyfin-port>
          key: "{{HOMEPAGE_VAR_JELLYFIN_KEY}}"
          version: 2            # Jellyfin 10.12+ は 2
          enableBlocks: true    # movies/series/episodes/songs を表示
          enableNowPlaying: true
    - Navidrome:
        href: http://192.168.0.222:4533
        icon: navidrome.png
        widget:
          type: navidrome
          url: http://192.168.0.222:4533
          user: <navidrome-user>
          salt: <randomsalt>
          token: "{{HOMEPAGE_VAR_NAVIDROME_TOKEN}}"   # = md5(password + salt)
          # 表示フィールドは固定（設定不可）
    - Stash:
        href: http://192.168.0.222:<stash-port>
        icon: stash.png
        widget:
          type: stash
          url: http://192.168.0.222:<stash-port>
          key: "{{HOMEPAGE_VAR_STASH_KEY}}"
          fields: ["scenes", "images", "galleries", "performers"]   # 先頭4のみ表示
    - Calibre-web:
        href: http://192.168.0.222:<calibre-port>
        icon: calibre-web.png
        widget:
          type: calibreweb
          url: http://192.168.0.222:<calibre-port>
          username: <calibre-user>
          password: "{{HOMEPAGE_VAR_CALIBRE_PASSWORD}}"
          fields: ["books", "authors", "series"]
    - LANraragi:
        href: http://192.168.0.222:<lrr-port>
        icon: lanraragi.png     # widget 無し → リンクのみ
- PKM:
    - Paperless-ngx:
        href: http://192.168.0.222:8010
        icon: paperless.png
        widget:
          type: paperlessngx
          url: http://192.168.0.222:8010
          key: "{{HOMEPAGE_VAR_PAPERLESS_KEY}}"
          fields: ["total", "inbox"]   # inbox = 未処理件数（PKM アクションアイテム）
- 制御:
    - ntfy:
        href: http://192.168.0.222:<ntfy-port>
        icon: ntfy.png
        widget:
          type: ntfy
          url: http://192.168.0.222:<ntfy-port>
          topic: <borg-通知トピック>
          # key: "{{HOMEPAGE_VAR_NTFY_KEY}}"   # 認証ありなら（tk_ 始まり）
          fields: ["title", "message", "priority", "lastReceived"]
    - Homepage:
        href: http://192.168.0.222:3001
        icon: homepage.png
```

Navidrome の token 生成（一度だけ）:
```sh
SALT=$(openssl rand -hex 8); echo "salt=$SALT"
printf '%s' "<password>${SALT}" | md5sum | cut -d' ' -f1   # → これが token
```

#### widgets.yaml（情報ウィジェット・盛り）

```yaml
- greeting:
    text_size: xl
    text: morikawa
- datetime:
    text_size: l
    format: { dateStyle: short, timeStyle: short }
- search:
    provider: duckduckgo
    target: _blank
- openmeteo:                 # キー不要
    latitude: <lat>
    longitude: <lon>
    units: metric
    cache: 5
- resources:                 # まずこれで CPU/RAM/disk/温度/uptime
    cpu: true
    memory: true
    disk: /                  # 複数マウントは disk を配列で並べる
    cputemp: true
    uptime: true
    units: metric
# さらに盛るなら glances（NAS で `glances -w` を別途常駐させる必要あり）:
# - glances:
#     url: http://192.168.0.222:61208
#     metric: cpu            # cpu/memory/process/network/fs/sensors を別カードで複数並べられる
```

#### NAS 側 Homepage コンテナ env（.env に・gitignore 済）

```sh
HOMEPAGE_ALLOWED_HOSTS=192.168.0.222:3001
HOMEPAGE_VAR_IMMICH_KEY=...
HOMEPAGE_VAR_PAPERLESS_KEY=...      # ← ser7 sops の値と同じトークンを NAS にも置く
HOMEPAGE_VAR_JELLYFIN_KEY=...
HOMEPAGE_VAR_STASH_KEY=...
HOMEPAGE_VAR_NAVIDROME_TOKEN=...
HOMEPAGE_VAR_CALIBRE_PASSWORD=...
# HOMEPAGE_VAR_NTFY_KEY=...
```

#### 盛った後の削り方

1. 全部 deploy して 1 週間使う。
2. **視線が行かなかった widget / カードを消す**（消すのも yaml 1 ブロック削除、ホットリロード）。
3. 残す widget も `fields` を実際に見る 1〜2 個に絞る（4 個上限もあるので並べ替え）。
   - 経験的に効くのは: Paperless `inbox` / Immich `storage` / ntfy 直近通知 / docker のコンテナ落ち検知。
4. 削った結果を §10 ④ にメモ更新 → これが「必要なものだけ」の確定形。

### 完了後

board の「いま着手可能」表と「完了済 sprint アーカイブ」を更新する。

---

## 11. CLI ツール追加（Mac 編集 → ser7 で build 検証）

気に入って追加したツール。Mac には nix が無く build 検証できないため、ser7 で `nhs`（または `home-manager build`）して通るか確認する。`tools.nix` には追加済。

- **bottom** — 既存（追加済だった）。`tools.nix:17`。何もしなくてよい。
- **serpl** — ripgrep+sed の対話 TUI。複数ファイル横断の find&replace を navigate-first で。`tools.nix` の「Rust CLI 追加」に追加済。`nhs` 後 `serpl` で起動確認。
- **uutils-coreutils-noprefix** — Rust 製 coreutils を**素の名前**（`ls`/`cp`/`mv` 等）で GNU coreutils の代わりに使う構成を選択。
  - **ser7 で要確認**: home-manager profile の bin が PATH で system coreutils より優先されるか（`which ls` が `~/.nix-profile/bin/ls` 等を指すか）。優先されないと素の名前では uutils が呼ばれない。
  - **build collision 注意**: 同一 profile に GNU coreutils と両方入ると衝突警告が出ることがある。home.packages 側には coreutils を明示していないので通常は出ないはずだが、出たら `lib.hiPrio` で優先度付けを検討。
  - 挙動差（GNU 拡張オプション非対応など）でスクリプトが転ぶ可能性があるので、合わなければ noprefix をやめて prefix 版（`uutils-coreutils`）か個別バイナリに切替。

