# Hermes Agent / NAS コンテナ構成 横断分析

調査日: 2026-07-06
対象: ser7 (NixOS) の Hermes agent 構成 (`home/modules/ai/`, `nixos/modules/system/networking.nix`, `~/.hermes/`) と NAS (192.168.0.222) の Docker コンテナ構成 (`~/services/`)

---

## 1. Hermes Agent (ser7)

### 構成の現状

- `home/modules/ai/hermes.nix` — Discord bot を systemd user service (`hermes-discord`) として起動
- `home/modules/ai/hermes-webui.nix` — nesquena/hermes-webui を user service (`hermes-webui`, port 8787) として起動
- `home/modules/ai/hermes-package.nix` — flake input `NousResearch/hermes-agent` に自前パッチ (`hermes-safe-tmp-deletes.patch`) を当てて uv2nix でビルド
- `nixos/modules/system/networking.nix` — Tailscale Serve で WebUI を `https://ser7.taild4ba88.ts.net/` に公開
- ランタイム設定・状態は `~/.hermes/`(config.yaml, auth.json, state.db 227MB, memories, kanban 等)

### 問題点

#### 🔴 P1: `GATEWAY_ALLOW_ALL_USERS=true` が Discord の許可リストを無効化している疑い

`hermes.nix:19-20` で `GATEWAY_ALLOW_ALL_USERS=true` と `DISCORD_ALLOWED_USERS=3839...` を同時に設定している。名前から見て前者は全ユーザー許可のグローバルスイッチで、後者の allowlist と矛盾する。bot が参加しているサーバー/チャンネルにアクセスできる第三者がエージェント(シェル実行能力あり)を操作できる可能性がある。意図的でなければ `GATEWAY_ALLOW_ALL_USERS` を削除し、allowlist のみで運用すべき。

#### ✅ P2: ser7 の `~/.hermes` バックアップ(対応済み 2026-07-06)

`home/modules/ai/hermes-backup.nix` を新設。systemd user timer が毎晩 02:30 JST に `~/.hermes` を NAS の `~/backup/ser7-hermes/` へ同期し(SQLite は `sqlite3 .backup` で整合スナップショット)、NAS の restic が 12:00 JST にそれごと B2 へバックアップする。logs / caches / bin / lsp / sandboxes は除外。

備考: UGOS の rsync はサーバー側パッチ(`ug_start_server` のパス検証)で ssh 経由の受信をすべて `invalid path` で拒否するため使用不可。tar over ssh + リモート側アトミック入れ替えで実装した。

#### 🟠 P3: `config.yaml` が手動管理で、実際に破損歴がある

`config.yaml.corrupt.20260629-210929.bak` など破損・復旧の痕跡が複数残っている。15KB の設定が Nix 管理外・バックアップ外・git 管理外で、agent 自身が書き換える運用。最低限、重要部分(model/provider/toolsets/kanban 設定)を dotfiles にリファレンスとして保存するか、定期スナップショットを取るべき。

#### 🟠 P4: user unit の `network-online.target` 依存は効いていない

`hermes.nix:12-13` / `hermes-webui.nix:25-26` の `After=network-online.target` は **systemd user インスタンスには存在しないターゲット**で、依存関係は黙って無視される。ブート直後はネット未接続のまま起動 → 失敗 → `Restart=on-failure` で回復、という動きに依存している。しかも `hermes-discord` には `StartLimitIntervalSec`/`StartLimitBurst` がない(WebUI 側にはある)。回線断が長引くと 15 秒間隔で無限再起動する。修正案:
- `RestartSec` を伸ばす + `StartLimit*` を両ユニットに揃える
- もしくは起動スクリプト冒頭で疎通待ちループを入れる

#### 🟠 P5: WebUI が tailnet 全体に生 HTTP (8787) でも露出

`hermes-webui.nix:51` で `0.0.0.0` bind。firewall は LAN からの 8787 を塞ぐが、`trustedInterfaces = [ "tailscale0" ]` により **tailnet の全デバイスから HTTP 8787 へ直アクセス可能**。Tailscale Serve (443/HTTPS) と経路が二重になっている。tailnet が自分の端末のみなら許容範囲だが、Serve に一本化するなら `127.0.0.1` bind に変更するのが素直。

#### 🟡 P6: WebUI のメモリピーク 8.9GB、リソース制限なし

`systemctl status` でピーク 8.9GB + swap 使用を確認。`MemoryMax=` / `MemoryHigh=` が未設定で、暴走時にデスクトップ全体を巻き込む。`MemoryHigh=4G` 程度の設定を推奨。

#### 🟡 P7: 使っていない extras による依存肥大

`hermes-package.nix:10-29` で dingtalk / feishu / modal / daytona / fal / azure-identity / bedrock など多数の extra を有効化。実際に使うのは Discord + ntfy + anthropic/openrouter 系のはず。ビルド時間・クロージャサイズ・攻撃面が無駄に増える。使っている機能だけに絞るべき。

#### 🟡 P8: 自前パッチの維持コスト

`hermes-safe-tmp-deletes.patch`(105 行、`tools/approval.py` への機能追加)を flake input に当て続けている。upstream 更新のたびに衝突リスクがある。upstream に PR を出すか、hook/設定で代替できないか検討。

#### 🟡 P9: シークレット管理が二重体系

Discord token は SOPS (`/run/secrets/discord_bot_token`) 経由なのに、`ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY` 等は `~/.hermes/.env` に平文(600 なので即危険ではない)。SOPS に寄せて `.env` を生成する形に統一すると管理が一本化する。

#### ℹ️ 補足

- `hermes-webui-tailscale-serve` は oneshot だが serve 設定自体は tailscaled 側で永続するため実害なし
- nixpkgs input が 2026-05-07 と 2 ヶ月古い(hermes-agent は 06-23)
- Discord unit で「Opus codec not found — voice playback disabled」警告。voice extras を入れているのに codec 不足で機能していない

---

## 2. NAS コンテナ構成

### 構成の現状

20 スタック(`~/services/*`)、稼働 25 コンテナ。バックアップは restic コンテナが毎日 B2 へ(直近成功: 2026-07-06、15 snapshots)。

### 問題点

#### 🔴 P10: `.env` のパーミッションが 777(シークレット全露出)

```
-rwxrwxrwx backup/.env     ← RESTIC_PASSWORD + B2 キー + DB パスワード
-rwxrwxrwx homepage/.env
-rwxrwxrwx immich/.env
-rwxrwxrwx karakeep/.env
-rwxrwxrwx paperless/.env
```

特に `backup/.env` は **restic リポジトリのパスワードと B2 認証情報**を含み、world-readable/writable。NAS 上の任意プロセス・ユーザーが読める&改ざんできる。miniflux / tailscale / beszel は 600 になっており整合性もない。

**✅ 修正済み (2026-07-06)**: 全 `.env` を `chmod 600` に統一(拡張 ACL はなし)。追加調査で compose ファイル 4 件(immich / beszel / miniflux / paperless)にも DB・admin パスワードが平文で入っており 777 だったため、これらも 600 に修正。残りの world-readable なシークレットファイルはスイープで検出なし。長期的には compose 内の平文シークレットを `.env` 参照に移すのが望ましい。

#### ✅ P11: immich-machine-learning の unhealthy(解決済み 2026-07-06)

調査の結果、ML サーバー自体は正常稼働しており(ping 200、手動 healthcheck 成功)、Docker デーモン側の healthcheck 実行がコンテナ起動時から失敗し続けていた(失敗ストリーク 31,504 回 ≒ 12.7 日)だけだった。`docker restart immich-machine-learning` で healthy に復帰。

メモリ影響: アイドル時 ~50-250MB、モデルはオンデマンドロード + 5 分無活動でアンロード。空き 2.4GB で日常利用は問題なし。ただし全ライブラリ再インデックスは swap 圧迫(既に 4.6GB 使用)するため夜間推奨。保険として `mem_limit: 2g` の追加を検討。

#### 🟠 P12: filebrowser 停止(7/1 から)

filebrowser が `Exited` のまま。使っていないなら compose ごと整理、使うなら復旧が必要。

※ wger スタックの停止は**意図的**(再開予定なし)と確認済み。問題ではないが、`docker compose down -v` + ディレクトリ削除で volume ごと整理可能(データは消える)。

#### 🟠 P13: バックアップ対象の欠落

restic の対象外になっているもの:

| サービス | 欠落データ |
|---|---|
| miniflux | ✅ **対応済み (2026-07-06)**: backup コンテナを miniflux_default に接続し pg_dump を追加 |
| stash | 設定・DB・メタデータ |
| calibre (cwa) | ライブラリ DB(data 配下なら間接的にカバーの可能性あり、要確認) |
| ntfy | 設定・購読キャッシュ(軽微) |
| gitadora-wiki | コンテンツ(git 管理済みなら不要) |

immich / paperless は pg_dump 済みで良好。miniflux は最低限追加すべき。

#### 🟠 P14: ほぼ全イメージが `:latest` / タグなしで再現性ゼロ

navidrome / miniflux / paperless / immich(`:release`)/ stash / homepage 等が `latest` 系、lanraragi に至ってはタグなし。一方 meilisearch (`v1.41.0`) や alpine-chrome (`124`) は pin 済みで方針が不統一。`docker compose pull` した瞬間に何が入るか分からず、ロールバックもできない。特に **immich は server が `:release` で自動更新される一方、DB が `pgvecto-rs:pg14-v0.2.0` に固定**されており、Immich 本体は既に VectorChord への移行を進めているため、いずれ server 更新で起動不能になるリスクがある。少なくとも DB を持つサービス(immich / paperless / miniflux)は明示的なバージョン pin + 手動アップグレードにすべき。

#### 🟡 P15: 監視はあるが通知がない

beszel(メトリクス)と homepage(ダッシュボード)はあるが、「unhealthy が 12 日」「スタック全滅が 5 日」を検知できていない。ntfy が既に稼働しているので、`docker events` / healthcheck 監視 → ntfy 通知の小さなスクリプト(または autoheal 系コンテナ)を足すだけで解決する。

#### 🟡 P16: restic コンテナが起動のたびに apk install する構成

`alpine:3.21` 素のイメージに entrypoint で restic + postgresql16-client を毎回インストール。起動が Alpine CDN に依存し、実際にキャッシュ警告も出ている。CDN 側の変化でバックアップが静かに止まり得る。restic 公式イメージ + pg_dump 用サイドカー、もしくは Dockerfile を焼くべき。また status サーバー (8090) が `0.0.0.0` 公開だが実害は小さい。

#### 🟡 P17: adguardhome / glances は compose 定義のみでコンテナ未作成

デプロイ途中の残骸か未着手か不明。使わないならディレクトリごと削除、使うなら起動を。

---

## 3. 横断的な所見

1. **バックアップの非対称**: NAS 側は毎日 B2 に取れているが、ser7 側の Hermes 状態(記憶・認証・設定)はゼロ。エージェント運用の資産は実は ser7 側に集中している。
2. **シークレット管理が三体系**: ser7 SOPS / ser7 `~/.hermes/.env`(平文600)/ NAS `.env`(平文777)。少なくとも NAS の 777 は即時修正、可能なら SOPS→NAS 配布に統一。
3. **「止まっても気づかない」構造**: unhealthy 12日・スタック停止5日を検知する仕組みがない。ntfy は既にあるので、healthcheck→ntfy の導線を作るのが費用対効果最大。
4. **宣言性のばらつき**: ser7 は Nix で厳格に宣言的な一方、WebUI のソースコピー運用・`~/.hermes/config.yaml` 手動管理・NAS の `:latest` 群と、状態が流動的な場所ほど壊れた実績がある(config.yaml 破損、wger 停止)。

## 推奨対応順

1. ~~NAS `.env` を `chmod 600`~~(修正済み 2026-07-06)— P10
2. `GATEWAY_ALLOW_ALL_USERS` の意図確認と削除 — P1
3. ~~`~/.hermes` のバックアップ追加~~(対応済み 2026-07-06)— P2
4. ~~immich-ml~~(再起動で解決済み)+ healthcheck→ntfy 通知 — P11, P15
5. ~~miniflux DB をバックアップ対象に追加~~(対応済み 2026-07-06)— P13
6. filebrowser / adguardhome / glances の要否判断、wger の残骸整理 — P12, P17
7. immich の DB 移行計画とバージョン pin — P14
