# Mac 側セッションからの観察メモ

Mac 側の Claude Code セッションで気づいた、`docs/improvement-plan.md` に反映すべき情報を集約するファイル。
plan 本体は home 側 (ser7) で編集する運用のため、Mac からは本ファイルにためて引き渡す。

home 側で plan に反映したセクションは本ファイルから削除すること。

---


## 3. 追加導入候補（Mac 側セッションでの選定）

`home/modules/cli/tools.nix` `apps.nix` および `programs.*` 個別モジュール
(`git.nix`, `direnv.nix` 等) を含む全体をレビューして選定。

### 既導入を再確認したもの

レビュー過程で「未導入と誤認したが既に入っていた」もの。記録のため残す。

| パッケージ | 場所 |
|---|---|
| `lazygit` | `home/modules/cli/git.nix:27` (`programs.lazygit.enable`) + zsh alias `lg` |
| `direnv` + `nix-direnv` | `home/modules/shell/direnv.nix` (zsh integration 込み) |

### 確定: 入れる方向

| 優先度 | パッケージ | カテゴリ | 効く理由 |
|---|---|---|---|
| 中 | **carapace** | 統一タブ補完エンジン | 数百コマンドの引数補完を一発装備。zsh 既存補完と共存可。`gh`/`cargo`/`kubectl` 等が一気に賢くなる |
| 中 | **fclones** | 重複ファイル検出 | Rust 製。引っ越しを繰り返した環境のお掃除に。`~/Documents`/`~/Pictures` で効く |

### 様子見・温度低め

| パッケージ | カテゴリ | メモ |
|---|---|---|
| **gum** | TUI スクリプト部品 (Charm) | NAS ランチャパターンの拡張に効くが、現状の fzf 構成で十分動いている。3 個目を書く時の選択肢として保留 |

### 追加場所案

```nix
# home/modules/cli/tools.nix の home.packages に追加
carapace
fclones
gum            # 様子見枠。書きながら使いたくなれば
```

carapace は zsh 統合のため `programs.carapace.enable = true` を別途設定する手もあるが、
HM オプションが熟していない場合は `home.packages` + 手動の zsh init 行追加で対応。

### 検証

```bash
nix flake check
nh home switch
carapace --list | head
fclones --version
gum --version
```

### 運用メモ

- carapace は zsh 統合（`carapace _carapace` 系の eval）が必要。HM オプション側の有無を確認してから方式決定
- fclones は dry-run (`fclones group <dir>`) で確認 → `--rm-links` 等で実行、の順
- gum は paperless-browse 拡張時に「`gum choose` 試してみる」程度のスタンスで OK

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
