# Homelab サービスマップ

> このファイルは `tools/homelab_service_map.py` が生成する現在の運用地図。
> 目的・責務・変更時の確認は `docs/homelab-service-map.json` で管理し、稼働状態は生成時に取得する。

- 生成日時: 2026-07-16T21:54:43+09:00
- 状態の意味: `稼働` / `停止` は今回のDocker観測結果。`未観測` は停止ではなく取得できなかった状態。`未観測（unit不存在）` はmanifestにあるsystemd unitが存在しない状態を表す。

## NAS Docker

### 基盤・入口・監視

| プロジェクト | 現在の状態 | 目的 | 管理場所 | 観測 | 変更時に確認 |
|---|---|---|---|---|---|
| backup | 稼働: restic | resticでバックアップし状態を公開する | NAS ~/services/backup | snapshot + backup status | 対象・DB dump・復元経路 |
| beszel | 稼働: beszel, beszel-agent | NASとser7のホスト・コンテナを観測する | NAS ~/services/beszel | Beszel Hub | agent接続と負荷 |
| gatus | 稼働: gatus | 主要HTTP入口を外形監視し、ntfy通知とHermes調査を起動する | NAS ~/services/gatus | HTTP check + relay delivery | 監視対象・failure threshold・relay token・通知経路 |
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
| lanraragi | 稼働: lanraragi | アーカイブのタグと閲覧状態を管理する | NAS ~/services/lanraragi | container health + UI | library mount・database・backup |
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
| filebrowser | 停止: filebrowser | ファイルブラウザの再評価候補 | NAS ~/services/filebrowser | container state（monitorの意図的停止除外対象） | 用途の重複とmonitor除外を確認後に再開・削除を判断 |
| homebox | 停止: homebox | 資産・取扱説明書管理の再評価候補 | NAS ~/services/homebox | container state | 要件・スマホ利用・API適合を確認後に判断 |
| karakeep | 停止: chrome, meilisearch, web | ser7へ移設済みのロールバック元。データとComposeは削除せず停止状態で保持する | NAS ~/services/karakeep | container state（monitorの意図的停止除外対象） | ser7の実データと外部到達性を確認後に削除を判断 |
| miniflux | 停止: miniflux, miniflux-db | ser7へ移設済みのロールバック元。PostgreSQL dataとComposeは削除せず停止状態で保持する | NAS ~/services/miniflux | container state（monitorの意図的停止除外対象） | ser7のPostgreSQL・iris-news ingest・外部到達性を確認後に削除を判断 |

## ser7 の自動化・判断層

| Unit | 現在の状態 | 目的 | 管理場所 | 観測 | 変更時に確認 |
|---|---|---|---|---|---|
| n8n.service | active (running) | Pavlokなどのワークフローを実行する | nixos/modules/system/n8n.nix | systemd + Tailscale Serve | workflow実行・secret境界・公開範囲 |
| n8n-tailscale-serve.service | active (exited) | n8nをTailscale限定HTTPSで公開する | nixos/modules/system/n8n.nix | systemd + tailscale serve status | 8443のServe設定と外部到達性 |
| nas-monitor-heartbeat.timer | active (waiting) | NAS monitor自身の停止を別経路で検出する | nixos/modules/system/nas-monitor-heartbeat.nix | systemd timer + ntfy JSON Lines | heartbeat timeoutと通知先 |
| borgbackup-job-home.timer | active (waiting) | ser7のホームディレクトリをNAS上のBorgリポジトリへ毎日バックアップする | nixos/modules/system/backup.nix | systemd timer + Borg snapshot | 対象パス・CIFS mount・復元経路・失敗通知 |
| obsidian-rsync.timer | active (waiting) | Obsidian VaultをNASへ毎時同期する | nixos/modules/system/backup.nix | systemd timer + rsync result | CIFS mount・同期先・削除反映 |
| iris-news-build.timer | active (waiting) | iris-newsの日次紙面生成を起動する | nixos/modules/system/iris-news.nix | systemd timer + build result | Miniflux ingest・生成物・OnSuccess publish |
| iris-news-publish.service | inactive (dead) | iris-newsの静的成果物をNAS公開領域へ同期する | nixos/modules/system/iris-news.nix | systemd oneshot + rsync result | CIFS mount・index更新・NAS Caddy配信 |
| iris-news-api.service | active (running) | NAS Caddy向けにiris-newsのsignal APIを提供する | nixos/modules/system/iris-news.nix | systemd service + NASからのAPI到達性 | NAS限定firewall・Karakeep連携・API応答 |
| iris-news-static.service | active (running) | iris-newsの静的紙面をloopbackで配信する | nixos/modules/system/iris-news.nix | systemd service + localhost HTTP | 生成ディレクトリ・8788 listener・HTML応答 |
| iris-news-tailscale-serve.service | active (exited) | iris-newsの静的紙面をTailscale限定で公開する | nixos/modules/system/iris-news.nix | systemd oneshot + tailscale serve status | /iris-news path・静的server・外部到達性 |
| hermes-monitoring-relay.service | active (running) | Gatus alertを認証・正規化してHermes webhookへ渡す | nixos/modules/system/monitoring-relay.nix | systemd service + /health + NAS reachability | SOPS secret・NAS限定firewall・Webhook V2署名 |
| hermes-discord.service | active (running) | HermesのDiscord会話入口を提供する | home/modules/ai/hermes.nix | systemd user service | allowlist・gateway所有・failure notification |
| hermes-webui.service | active (running) | Hermes WebUIを提供する | home/modules/ai/hermes-webui.nix | systemd user service + Tailscale | loopback bind・memory limit・公開経路 |
| hermes-webui-tailscale-serve.service | active (exited) | Hermes WebUIをTailscale限定HTTPSで公開する | nixos/modules/system/networking.nix | systemd oneshot + tailscale serve status | loopback WebUI・Serve設定・外部到達性 |
| beszel-agent.service | active (running) | ser7をBeszelへ観測対象として接続する | home/modules/ai/beszel-agent.nix | systemd user service | agent接続とPodman state |
| karakeep.service | active (running) | ブックマークと保存状態をrootless Podmanで管理する | home/modules/ai/karakeep.nix | systemd user service + Podman + Tailscale HTTPS | web・Meilisearch・Chromeの連携、Borg snapshot、外部到達性 |
| miniflux.service | active (running) | RSS購読と既読状態をrootless Podman PostgreSQLで管理する | home/modules/ai/miniflux.nix | systemd user service + Podman + Tailscale HTTPS | PostgreSQL restore、iris-news ingest、Borg snapshot、外部到達性 |
| bedtime-pavlok-vibe.service | 未観測（unit不存在） | 従来の就寝時Pavlok vibe発火を担う | home/modules/desktop/pavlok.nix | systemd user service | n8n移行後の二重発火を確認 |

## 更新ルール

1. NAS Composeやser7のunitを追加・削除・役割変更したら、まず `docs/homelab-service-map.json` の目的・責務・確認項目を更新する。
2. その後 `python3 tools/homelab_service_map.py` を実行し、観測結果をこのファイルへ反映する。
3. 生成結果の差分を読み、意図しない停止・未観測・責務の重複がないか確認する。
4. 秘密値、API token、`.env` の内容はこの地図へ書かない。
