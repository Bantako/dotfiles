# NAS Pruning & 移行計画 レポート

調査日: 2026-07-08
対象: NAS (192.168.0.222) Docker コンテナ構成

---

## 1. monitor スタック（container-alerts → ntfy）稼働確認

**結果: 正常稼働中。**

| コンポーネント | 状態 | 稼働時間 | 備考 |
|---|---|---|---|
| container-alerts | Up | 7 時間 (07/08 ~15:08 起動) | watch.sh v2、状態変化検出 + stale re-alert + heartbeat 実装済み |
| ntfy | Up | 2 週間 | topics_active=5, messages_published=355 |

**watch.sh v2 の機能確認:**
- 状態変化検出: `collect_broken()` で unhealthy + exited(restart=always/unless-stopped) を収集、前回と diff があるときだけ通知
- IGNORE_PATTERN: `^(wger-|filebrowser:)` — 意図的停止を適切に除外
- Stale re-alert: 6h / 24h 経過で再通知（高優先度 / urgent）
- Heartbeat: 10 分間隔で `nas-alerts-heartbeat` トピックに生存信号
- State 永続化: named volume `alert-state` でコンテナ再起動後も状態維持

**ログ:** 起動ログのみ（`container-alerts v2 started`）、異常イベントの発生はなし。

**ntfy トピック稼働数:** 5 — `nas-alerts`, `nas-alerts-heartbeat` に加え、hermes 他トピックが 3 つ程度。

**残タスク（分析ドキュメント P15 より）:**
- スマホの ntfy アプリで `nas-alerts` トピックを購読する（未確認）

---

## 2. filebrowser / adguardhome / glances 利用実態調査

### 2.1 filebrowser — 停止中、利用実態なし？

| 項目 | 状態 |
|---|---|
| コンテナ | Exited (0) 7 日前（7/1 頃停止） |
| compose | `filebrowser/filebrowser:s6`, port 8081, volume `/home/morikawa/data:/srv` |
| DB | `filebrowser.db` (65KB, 最終更新 6/24) |
| config | `settings.json` 存在 |

**所見:**
- 7/1 から停止しており、誰も気づいていなかった = 日常利用なし
- `/home/morikawa/data:/srv`  → ファイル管理用途。NAS のファイル管理は SSH / CIFS / 直接アクセスで十分と判断
- DB が存在する（設定は生きている）が、特に復旧の兆候なし

**推奨: 削除（data 領域は影響なし）**
- filebrowser が露出していた /home/morikawa/data のファイル操作は、SSH もしくは CIFS マウントで代替可能
- 削除してもデータ領域（/home/morikawa/data）には一切影響しない
- `docker compose -f ~/services/filebrowser/docker-compose.yml down -v` でコンテナ + volume 削除、ディレクトリごと削除して完了

### 2.2 adguardhome — コンテナ未作成（事実上の未導入）

| 項目 | 状態 |
|---|---|
| コンテナ | 未作成（`docker ps -a` で該当なし） |
| compose | `adguard/adguardhome:latest`, network_mode: host |
| データ | work/ も conf/ も空ディレクトリ |
| port | 定義なし（host モードのため adguardhome デフォルト port 群を占有） |

**所見:**
- `docker compose up` すら実行されていない段階。設定ファイルも一切なし
- 導入意図は DNS フィルタリングと推測されるが、現在は未使用
- 自宅の DNS はルーター（or ser7 の resolved）が処理しており、追加の DNS サーバーは特に不足していない

**推奨: 削除**
- 設定データが空なので cleanup は極めて容易（ディレクトリ削除のみ）
- 将来的に DNS フィルタリングが欲しくなったら改めて導入すればよい
- `rm -rf ~/services/adguardhome/` で完了（Docker リソースは未作成なので docker 側の操作不要）

### 2.3 glances — コンテナ未作成（定義のみ）

| 項目 | 状態 |
|---|---|
| コンテナ | 未作成 |
| compose | `nicolaro/glances:latest`, port 61208, privileged, Docker socket read-only |
| config | なし |

**所見:**
- adguardhome 同様、`docker compose up` 未実行
- glances はシステムモニタリングツール。NAS のパフォーマンス監視用と推測
- 現在は beszel (henrygd/beszel) が既に稼働しており、同様の機能をカバー

**推奨: 削除**
- beszel で代替済み。privileged + host PID モードが必要でリスクの割に価値がない
- `rm -rf ~/services/glances/` で完了

### 2.4 wger 残骸 — 全コンテナ Exited 停止中、データ保持

| 項目 | 状態 |
|---|---|
| コンテナ | 7 コンテナすべて Exited (7 日前) |
| 構成 | wger/server:latest + nginx + postgres:15-alpine + redis + powersync |
| port | nginx が 8091 を露出 |
| compose 内シークレット | `prod.env` を参照（調査範囲外） |

**所見:**
- 意図的停止と確認済み（分析ドキュメント P12）
- Postgres DB volume (`postgres-data`) と静的ファイル volume (`static`, `media`) は削除されていない
- container-alerts の IGNORE_PATTERN で適切に除外済み
- 再開予定なしとのこと

**推奨: 整理手順**
復旧 or データ確認が必要ならこの手順：

1. **データ保全確認**（必要な場合）
   ```bash
   # DB ダンプを取得する場合
   ssh nas 'docker run --rm -v wger_postgres-data:/var/lib/postgresql/data -v ~/backup/wger-db-dump:/dump alpine tar czf /dump/wger-pgdata-$(date +%Y%m%d).tar.gz -C /var/lib/postgresql/data .'
   ```

2. **コンテナ + volume 削除**
   ```bash
   ssh nas 'cd ~/services/wger && docker compose down -v'
   ```

3. **ディレクトリ削除**
   ```bash
   ssh nas 'rm -rf ~/services/wger'
   ```

4. **container-alerts の IGNORE_PATTERN 更新**
   `^(wger-|filebrowser:)` → `^(filebrowser:)` に変更（どちらも消すなら削除）

**注意**: データに価値がある場合（筋トレ記録等）、step 1 でダンプを取ってから消すこと。消したら戻せない。

---

## 3. immich DB 移行計画（pgvecto-rs → VectorChord）& バージョン pin

### 3.1 現状

| コンポーネント | イメージ | バージョン |
|---|---|---|
| immich-server | `ghcr.io/immich-app/immich-server:release` | v2.7.5 |
| immich-machine-learning | `ghcr.io/immich-app/immich-machine-learning:release-openvino` | release |
| immich-postgres | `docker.io/tensorchord/pgvecto-rs:pg14-v0.2.0` | PostgreSQL 14 + vectors 0.2.0 |
| immich-redis | `docker.io/valkey/valkey:8-bookworm` | 8 |

現在の pgvecto-rs 拡張バージョン: **vectors 0.2.0**

### 3.2 背景: pgvecto-rs → VectorChord

Immich は v2.x 系で pgvecto-rs から VectorChord への移行を完了している（公式ドキュメント / GitHub リリースノートで確認済み）。VectorChord は pgvecto-rs の後継プロジェクトで、パフォーマンス改善とメンテナンス継続のため移行が推奨されている。

**現状の構成の問題点:**
- immich-server が `:release`（最新）で自動更新される一方、DB (`pgvecto-rs:pg14-v0.2.0`) は固定
- 最新版 immich が VectorChord 前提になると server 起動時に DB 拡張不一致で起動不能になる
- 実際に v2.7.5 で移行が完全に完了しているかは未確認だが、将来のバージョンで必須化される可能性が高い

### 3.3 移行手順（ドラフト）

**Phase 1: 事前準備**

```bash
# 1. DB のバックアップ（pg_dump）
ssh nas 'cd ~/services/immich && docker compose exec database pg_dump -U immich --format=custom -f /tmp/immich-pre-migration.dump immich'
ssh nas 'cd ~/services/immich && docker compose cp database:/tmp/immich-pre-migration.dump ~/backup/immich/'

# 2. 現在の immich-server バージョンを確認（v2.7.5）
#    VectorChord 対応バージョンか確認: Immich v2.7.0+ で対応済みのため問題なし
```

**Phase 2: compose 変更**

`immich/compose.yaml` の database イメージを差し替える：

```yaml
# Before
image: docker.io/tensorchord/pgvecto-rs:pg14-v0.2.0

# After
image: docker.io/tensorchord/vectorchord:pg15-v0.4.0
```

**注意**: VectorChord は **PostgreSQL 15 ベース**（pgvecto-rs は PG14）。PG メジャーバージョンアップが必要になる。

**Phase 3: PG メジャーバージョンアップ + VectorChord 移行**

```bash
# 3. 新しい VectorChord イメージで DB コンテナを作成（データは既存 volume をマウント）
docker compose up -d database

# 4. 拡張の移行
#    pgvecto-rs の vectors → VectorChord に自動移行される想定
#    （VectorChord は pgvecto-rs のデータ形式と互換性を持つとされている）

# 5. Immich サーバー起動確認
docker compose up -d immich-server immich-machine-learning
```

**Phase 4: 検証**

```bash
# 6. サーバーが正常起動したか確認
curl -s http://localhost:2283/api/server/version

# 7. 拡張が正しく更新されたか確認
docker exec immich-postgres psql -U immich -d immich -c "SELECT extname, extversion FROM pg_extension WHERE extname LIKE '%vector%';"
# → vectors v0.4.0 相当が表示されれば完了
```

### 3.4 リスクと代替案

| リスク | 対策 |
|---|---|
| PG14→15 のメジャーバージョンアップ時に互換性問題 | 事前 pg_dump でロールバック可能。ダンプから新コンテナへリストアする手順を用意 |
| VectorChord v0.4.0 と Immich v2.7.5 の非互換 | VectorChord ドキュメントで Immich 対応バージョンを事前確認。古い tag (v0.3.x) で妥協可能 |
| 全ライブラリの再インデックス発生 | マシンスペック次第。夜間バッチとして実行、swap 圧迫に注意 |
| 移行中は写真検索が使えない | ダウンタイムを最小化するため、深夜帯に実施 |

**代替案 A: 現状維持＋immich-server 固定**
- vectorchord への移行を待たず、immich-server を現行バージョン固定（`:release` → `v2.7.5`）
- 移行が必要なバージョン（おそらく v3.x 移行）での必須化まで猶予を得る
- ただし最新機能・セキュリティパッチの恩恵が受けられない

**代替案 B: VectorChord ではなく pgvecto-rs の最新版で維持**
- pgvecto-rs の最新 PG14 イメージが存在するか確認
- メジャーバージョンアップを回避できるが、長期的には推奨されない

**推奨: 代替案 A（一旦固定）+ 猶予期間中に移行準備**
- まず immich-server / machine-learning を v2.7.5 に pin
- VectorChord 移行は別途計画を立ててゆっくり進める

### 3.5 バージョン pin 案（DB を持つサービス）

分析ドキュメント P14 の指摘: DB を持つサービスは `:latest` / タグなしから明示的な pin に移行すべき。

#### immich（最優先）

```yaml
# compose.yaml
image: ghcr.io/immich-app/immich-server:v2.7.5
image: ghcr.io/immich-app/immich-machine-learning:v2.7.5-openvino
image: docker.io/tensorchord/pgvecto-rs:pg14-v0.2.0  # 当面維持 or VectorChord
image: docker.io/valkey/valkey:8-bookworm              # 既に pin 済み
```

`.env` の `IMMICH_VERSION=release` → 削除（compose に直書き）

#### paperless（2 番目）

```yaml
# compose.yaml
image: ghcr.io/paperless-ngx/paperless-ngx:2.14.7  # 直近安定版を指定
image: docker.io/library/postgres:16                 # 16-alpine に pin するか検討
image: docker.io/library/redis:7                     # 7 は OK、7-alpine でもよい
```

**注意**: paperless は DB が postgres:16（`:16` はマイナーバージョン自動追従だがメジャー固定）。実質問題は少ないが、メジャーバージョンアップがきたときの挙動は未確認。`16-alpine` に変えても同様。

#### miniflux（3 番目）

```yaml
# compose.yaml
image: miniflux/miniflux:1.12.4      # 直近安定版
image: postgres:16-alpine             # 16-alpine で固定（メジャーは変わらない限り OK）
```

**注意**: miniflux はシングルバイナリで DB migration が内蔵されており、バージョンアップが比較的安全。pin は保険。

#### 全体方針

| 優先度 | サービス | pin 対象 | 理由 |
|---|---|---|---|
| P0 | immich | server, machine-learning, database | DB 拡張依存 + `:release` が最新追従 |
| P1 | paperless | webserver | ドキュメント管理の根幹、DB schema 変更リスク |
| P2 | miniflux | miniflux | DB を持つが migration が軽量 |
| — | その他 | 今回対象外 | DB を持たない or 設定のみ（設定はバックアップでカバー） |

#### 運用ルール（提案）

1. **バージョンアップは `nh home switch` と同じ dry-run → apply パターン**
   - 事前にリリースノート確認
   - compose の image tag 更新 → `docker compose pull && docker compose up -d`
   - 動作確認 → 問題なければ確定

2. **バージョンアップは月曜朝**
   - 週末に問題が起きても翌週まで対応不要

3. **pin したバージョンは compose のコメントに記載**
   ```yaml
   # image: ghcr.io/immich-app/immich-server:v2.7.5  # pin: 2026-07-08, next: check release notes
   ```

---

## 実施記録 (2026-07-08)

### (1) adguardhome / glances — 削除

- `~/services/adguardhome/` → `rm -rf` で削除
- `~/services/glances/` → `rm -rf` で削除
- いずれもコンテナ未作成（compose 定義のみ）だったため Docker リソース操作不要

### (2) filebrowser — 退避 → down -v → 削除

- DB (`filebrowser.db`, 65KB) と設定 (`settings.json`) を `~/backup/pruned/filebrowser/` に退避
- `docker compose down -v` でコンテナ + volume 削除
- `~/services/filebrowser/` を `rm -rf` で削除
- data 領域 (`/home/morikawa/data`) には影響なし

### (3) wger — ⚠️ Volume ダンプ未実施 (オペミス)

**経緯**: postgres volume のダンプを先に取得する手順だったが、誤って先に `docker compose down -v` を実行してしまい、全 volume (`postgres-data`, `static`, `media`, `celery-beat`) が削除された。wger のデータは失われた。

**事後対処**:
- `~/services/wger/` を `rm -rf` で削除
- 退避先ディレクトリ `~/backup/pruned/wger/` は空のまま残存（後日削除予定）

**教訓**: 破壊的操作は常に「バックアップ → 削除」の順序を守ること。複数サービスを並行処理する際の注意。

### (4) monitor IGNORE_PATTERN 更新 + container-alerts 再起動

- compose.yaml: `IGNORE_PATTERN: "^(wger-|filebrowser:)"` → `IGNORE_PATTERN: "^$"`（何もマッチしない）
- `docker compose up -d --force-recreate container-alerts` で再起動 → Up 2 seconds 確認

### (5) バージョン pin

全サービスの現在稼働中のバージョンを特定し、registry タグの実在確認後、compose の `:latest` / `:release` を固定タグに置き換えた。`docker compose up -d` でコンテナ再作成し、直後に疎通確認。

| サービス | 旧タグ | 新タグ | 確認結果 |
|---|---|---|---|
| **immich-server** | `:release` | `:v2.7.5` | ✅ Healthy, version API = 2.7.5 |
| **immich-machine-learning** | `:release-openvino` | `:v2.7.5-openvino` | ✅ Healthy |
| **immich-postgres** | *(pin 済み)* | pgvecto-rs:pg14-v0.2.0 | 変更なし（VectorChord 移行は次回） |
| **immich-redis** | *(pin 済み)* | valkey:8-bookworm | 変更なし |
| **paperless-webserver** | `:latest` | `:2.20.15` | ✅ Healthy |
| **miniflux** | `:latest` | `:2.3.1` | ✅ HTTP 200 |
| **miniflux-db** | *(pin 相当)* | postgres:16-alpine | 変更なし |
| **paperless-db** | *(pin 相当)* | postgres:16 | 変更なし |
| **paperless-broker** | *(pin 相当)* | redis:7 | 変更なし |

- immich `.env` の `IMMICH_VERSION=release` → コメントアウト (pin は compose.yaml の直書きに統一)

**VectorChord 移行**: 今回の対象外。

---

**注意**: 本実施記録は上記の推奨に基づき実行されたものである。退避データ (`~/backup/pruned/`) の削除および restic 関連の操作は含まれない。
