# Jelu → Grimmory 移行計画

作成: 2026-07-08 (Mac) / 実行: ser7 + NAS
背景: Jelu は日本語書誌が構造的に弱い(内蔵 4 プラグインに日本語経路なし)。Grimmory (BookLore の community fork, AGPL-3.0, v3.2.4) を本棚 UI + リーダー + 読了管理として採用し、書誌は hermes が openBD/NDL/PubDB を多段で引いて API 経由で書き込む分担にする。

## 方針

- **正本は Grimmory の DB に移す**が、撤退路として週次 API エクスポート(md/JSON)を初日から仕込む
- 移行はデータの引っ越しではなく**書誌の引き直し**を兼ねる(Jelu の貧弱なメタデータをそのまま運ばない)
- Jelu のデータは全量退避してから触る。ロールバックはいつでも可能な状態を保つ

## Phase 0: Jelu データの退避 (NAS)

- [ ] Jelu の SQLite DB ファイルをそのままコピーして退避(compose 停止中に取るのが安全)
- [ ] Jelu API で全データを JSON dump(books / reading events / tags)。トークンは sops 済み (2026-06-28)
  - 取得スクリプトは hermes に書かせてよい。dump は `~/backup/jelu-final/` へ
- [ ] 冊数・読了数を控えておく(移行後の検算用)

## Phase 1: Grimmory 試験デプロイ (NAS)

- [ ] `~/services/grimmory/` に compose 作成。**イメージはバージョン pin**(`:latest` 禁止 — NAS 分析 P14 の教訓)
- [ ] BookLore 互換の compose 形式(DB 名・ボリューム構成は Grimmory README の指定に従う)
- [ ] `.env` は最初から `chmod 600`(P10 の教訓)

### 受け入れテスト(順に、落ちたら中断)

1. **ファイルなし本の登録可否** — ISBN/タイトルのみのメタデータエントリを作れるか。
   Kindle/BW 購入本を台帳に載せる要件の生命線。BookLore 由来のファイル中心設計なので**ここが最大の未確認点**。
   UI で無理でも API (`/api/docs`, `API_DOCS_ENABLED=1`) で作れれば合格。
2. 日本語タイトル・著者の手動入力と検索が正常か
3. API 経由の書誌書き込み(タイトル・著者・書影 URL・説明)が通るか
4. 既存 Calibre-web のライブラリと自炊ファイルの二重管理にならない構成を決める
   (BookDrop の監視先を Calibre ライブラリに向けるか、当面ファイルは Calibre-web 続投で Grimmory は台帳専用にするか)

**テスト 1 が不合格の場合**: 移行中止。Jelu 続投 or 「ファイルなし本の置き場」を再設計する分岐に戻る。退避済みなので損害ゼロ。

## Phase 2: データ移行 (hermes 作業)

- [ ] hermes に移行スクリプトを書かせる: Jelu dump → 正規化 → 書誌引き直し → Grimmory API 書き込み
  - 正規化: ISBN-10→13 統一、読了状態(to-read/reading/read)と日付、評価のマッピング
  - 書誌引き直し: ISBN で openBD → NDL サーチ → PubDB の順に多段引き。全滅時は Jelu の値をそのまま使い、`needs-metadata` タグを付ける
- [ ] 冊数の検算(Phase 0 の控えと一致するか)。`needs-metadata` の残数を確認
- [ ] 書き込みは破壊的でないが、初回は 5 冊程度の dry-run で流してから全量

## Phase 3: 運用組み込み

- [ ] **週次エクスポートジョブ**(撤退路): Grimmory API → JSON/md を NAS に保存。restic の対象に入る場所へ
- [ ] Grimmory の DB を restic バックアップ対象に追加(P13 の教訓。DB dump 方式は DB の種類に合わせる)
- [ ] Homepage にエントリ追加、Jelu のエントリ削除
- [ ] hermes のツールとして「ISBN/タイトル → 書誌取得 → Grimmory 登録」を配線(出先の「この本買った」「持ってたっけ」チャネル)
- [ ] バージョン更新は手動運用(リリースノートを見てから上げる)

## Phase 4: Jelu 撤収

Phase 2-3 が安定して 2 週間程度問題なければ:

- [ ] `docker compose down`(volume はまだ消さない)
- [ ] `~/services/jelu/` を archive へ移動
- [ ] sops の Jelu API token を削除、dotfiles 側の参照 (`nixos/hosts/ser7/secrets/`) も掃除
- [ ] Homepage / 監視系から参照が残っていないか確認
- [ ] 1 か月後、退避 dump が残っていることを確認してから volume 削除

## 未確認事項(実行時に潰す)

- Grimmory のファイルなし本サポート(受け入れテスト 1)
- Jelu のエクスポート形式(API dump で足りるはずだが、CSV エクスポート機能があればそちらが楽)
- Grimmory の API 認証方式(トークン発行手順)
- Grimmory の DB 種別(BookLore は MariaDB 系だったはず → dump コマンドの選定)
