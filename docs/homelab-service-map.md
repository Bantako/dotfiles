# Homelab サービスマップ

> このファイルは `tools/homelab_service_map.py` が生成する現在の運用地図。
> 目的・責務・変更時の確認は `docs/homelab-service-map.json` で管理し、稼働状態は生成時に取得する。

- 生成日時: 2026-07-13T22:23:13+09:00
- 状態の意味: `稼働` は今回の観測結果、`未観測` は停止ではなく取得できなかった状態を表す。

## NAS Docker

### 基盤・入口・監視

| プロジェクト | 現在の状態 | 目的 | 管理場所 | 観測 | 変更時に確認 |
|---|---|---|---|---|---|
| backup | 稼働: restic | resticでバックアップし状態を公開する | NAS ~/services/backup | snapshot + backup status | 対象・DB dump・復元経路 |
| beszel | 稼働: beszel, beszel-agent | NASとser7のホスト・コンテナを観測する | NAS ~/services/beszel | Beszel Hub | agent接続と負荷 |
| homepage | 稼働: homepage | NASサービスの入口を集約する | NAS ~/services/homepage | HTTP health + Homepage widgets | リンク・widget・config reload |
| monitor | 稼働: container-alerts | unhealthy/exitedコンテナを検出して通知する | NAS ~/services/monitor | container-alerts heartbeat + ntfy | ignore対象と通知経路 |
| ntfy | 稼働: ntfy | 障害・運用通知を配送する | NAS ~/services/ntfy | HTTP health + publish path | 通知先と配送確認 |
| tailscale | 稼働: tailscale | NASをtailnetへ接続する | NAS ~/services/tailscale | container state + Tailscale status | node identity と外部到達性 |

### 個人データの正本

| プロジェクト | 現在の状態 | 目的 | 管理場所 | 観測 | 変更時に確認 |
|---|---|---|---|---|---|
| calibre | 稼働: cwa-main | 書籍ファイルの現行ライブラリを提供する | NAS ~/services/calibre | container health + UI | library path・metadata・backup |
| immich | 稼働: database, immich-machine-learning, immich-server, redis | 写真・動画を管理する | NAS ~/services/immich | HTTP health + Immich UI | DB互換性・画像処理・backup |
| jelu | 稼働: jelu | 読書管理の現行正本を持つ | NAS ~/services/jelu | HTTP UI | 移行・エクスポート・backup |
| karakeep | 稼働: chrome, meilisearch, web | ブックマークと保存状態を管理する | NAS ~/services/karakeep | container health + UI | web・Meilisearch・Chromeの連携 |
| lanraragi | 稼働: lanraragi | アーカイブのタグと閲覧状態を管理する | NAS ~/services/lanraragi | container health + UI | library mount・database・backup |
| miniflux | 稼働: miniflux, miniflux-db | RSS購読と既読状態を管理する | NAS ~/services/miniflux | container health + API | PostgreSQL・feed refresh・backup |
| navidrome | 稼働: navidrome | 音楽の再生状態とプレイリストを管理する | NAS ~/services/navidrome | HTTP UI | ライブラリ分割・DB・playlist |
| paperless | 稼働: broker, db, webserver | 書類を保管・検索する | NAS ~/services/paperless | container health + Homepage | DB dump・consumer・HTTP health |
| radicale | 稼働: radicale | CalDAV/CardDAVの正本を持つ | NAS ~/services/radicale | HTTP health + local calendar mirror | 認証・CalDAV同期・backup |
| stash | 稼働: stash | メディアの整理と検索を行う | NAS ~/services/stash | HTTP UI | storage headroom・SQLite・backup |

### 作業・公開物

| プロジェクト | 現在の状態 | 目的 | 管理場所 | 観測 | 変更時に確認 |
|---|---|---|---|---|---|
| gitadora-wiki | 稼働: api, caddy | GITADORA wiki APIとサイトを配信する | NAS ~/services/gitadora-wiki | HTTP response | API・Caddy・静的成果物 |
| iris-news | 稼働: caddy | iris-newsの公開物をCaddyで配信する | NAS ~/services/iris-news | HTTP response + generated paper | ser7 buildとのpublish接続 |

### 候補・停止中

| プロジェクト | 現在の状態 | 目的 | 管理場所 | 観測 | 変更時に確認 |
|---|---|---|---|---|---|
| homebox | 未観測 | 資産・取扱説明書管理の再評価候補 | NAS ~/services/homebox | 未稼働 | 要件・スマホ利用・API適合を確認後に判断 |

## ser7 の自動化・判断層

| Unit | 現在の状態 | 目的 | 管理場所 | 観測 | 変更時に確認 |
|---|---|---|---|---|---|
| n8n.service | active (running) | Pavlokなどのワークフローを実行する | nixos/modules/system/n8n.nix | systemd + Tailscale Serve | workflow実行・secret境界・公開範囲 |
| n8n-tailscale-serve.service | active (exited) | n8nをTailscale限定HTTPSで公開する | nixos/modules/system/n8n.nix | systemd + tailscale serve status | 8443のServe設定と外部到達性 |
| nas-monitor-heartbeat.timer | active (waiting) | NAS monitor自身の停止を別経路で検出する | nixos/modules/system/nas-monitor-heartbeat.nix | systemd timer + ntfy JSON Lines | heartbeat timeoutと通知先 |
| hermes-discord.service | active (running) | HermesのDiscord会話入口を提供する | home/modules/ai/hermes.nix | systemd user service | allowlist・gateway所有・failure notification |
| hermes-webui.service | active (running) | Hermes WebUIを提供する | home/modules/ai/hermes-webui.nix | systemd user service + Tailscale | loopback bind・memory limit・公開経路 |
| beszel-agent.service | active (running) | ser7をBeszelへ観測対象として接続する | home/modules/ai/beszel-agent.nix | systemd user service | agent接続とPodman state |
| bedtime-pavlok-vibe.service | inactive (dead) | 従来の就寝時Pavlok vibe発火を担う | home/modules/desktop/pavlok.nix | systemd user service | n8n移行後の二重発火を確認 |

## 更新ルール

1. NAS Composeやser7のunitを追加・削除・役割変更したら、まず `docs/homelab-service-map.json` の目的・責務・確認項目を更新する。
2. その後 `python3 tools/homelab_service_map.py` を実行し、観測結果をこのファイルへ反映する。
3. 生成結果の差分を読み、意図しない停止・未観測・責務の重複がないか確認する。
4. 秘密値、API token、`.env` の内容はこの地図へ書かない。
