# Hermes非同期監督型ワークシステム 要件仕様

作成日: 2026-07-21 (JST)<br>
状態: Accepted for MVP planning<br>
省トークン移行目標日: 2026-08-21

実装計画: [`plans/2026-07-21-hermes-supervisor-mvp.md`](plans/2026-07-21-hermes-supervisor-mvp.md)

---

## 1. 目的

人間がObsidianの細かなtask一覧から次の作業を選び、Agentへ都度指示する運用を置き換える。

あなたはHermes WebUIの`default` Profileで、思いつき・懸念・訂正・撤回・依頼を自然言語で随時投入する。Supervisorは入力を冷却・統合・深掘りし、少数の上位目的へ位置付け、低リスク作業を専門Agentへ委譲する。

人間は主に21:00の夜レビューへ参加し、重要な方針・承認・実環境適用だけを判断する。

本システムが最適化する対象はAgentの稼働量ではない。人間の注意を増やさず、現実の成果を安全に完遂すること。

## 2. 設計原則と暫定パラメータ

### 2.1 変更しない原則

- 判断の所有者は人間。Supervisorは材料・構造・推奨を出すが、権限拡大や重要方針を自己承認しない。
- readは広く、writeは狭くする。
- SupervisorとVerifierを分離する。SupervisorはVerifier不合格を単独で覆せない。
- 会話原文、Capture、判断理由、成果、検証結果を追跡可能にする。
- 共有資源へのwriteは資源ごとに単一Operatorへ限定する。
- Gitを変更履歴、Vault/ADRを長期判断履歴、runbook/Skillを手順の正本として使う。
- LLMを呼ばなくてよい処理は、決定論的script・状態機械・Skillへ移す。
- `05-Private/`は読まない。

### 2.2 暫定パラメータ

以下は現時点の最終決定ではなく、観測に応じて変更する初期値。

- activeな上位目的数
- 同時Worker数
- 一日あたりdispatch数
- Supervisor起動上限
- card runtime・retry・モデル昇格回数
- モデル割当
- 日次soft budget
- 夜ブリーフの判断件数上限
- Shadow / Limited liveの日数

変更時は「変更理由」「観測値」「戻す条件」を構造化ログへ残す。安全境界の緩和は人間承認を必須とする。

## 3. 成熟度モデル

### Stage 0: Bootstrap（開始から2026-08-21まで）

Codexを多く利用できる期間を、仕事量の最大化ではなく省トークン運用の構築へ投資する。

- activeな上位目的は**一つに固定**する。
- 目的内部だけを最大3 Agentで並列化する。
- 強いモデルをSupervisor・Verifier・設計・評価へ優先投入する。
- Capture誤分類、優先順位、失敗回復、Verifier判定の評価例を蓄積する。
- 成功した反復手順をscript・Skill・runbookへ抽出する。
- no-op判定、重複排除、cursor管理、budget判定を決定論的にする。
- モデルごとの成功率・コスト・runtime・人間修正率を計測する。

### Stage 1: Eco steady state（2026-08-21までに到達）

- idle時と無変更pollではLLMを一度も呼ばない。
- 一つの変更batchにつきSupervisor呼び出しは原則一回以内にする。
- 安価なWorkerを既定にし、強いモデルは形成・難問・高リスク検証・失敗時だけ使う。
- Capture・停止・復元・Kanban状態はCodex不在でも機能する。
- Codexが利用不能でも、仕事を失わず`schedule/review`へ安全に退避できる。
- 同じ事実を毎回再探索せず、source ID・artifact・Skillを再利用する。
- 3日間のLimited liveを初期budget内で完走する。

### Stage 2: Controlled expansion

Stage 1の合格後にだけ検討する。

- activeな上位目的を二つへ増やす。
- 完遂率、write競合、人間レビュー時間、コストが悪化しなければ最大三つへ増やす。
- 一度に一段階だけ変更する。
- 悪化時は直前の上限へ自動で戻し、理由を夜ブリーフへ出す。

## 4. ユーザー体験

### 4.1 入力

- 主入口はHermes WebUIの`default` Profile。
- 厳密なtask記法を要求しない。
- 全発言を自動実行依頼とはみなさない。
- `discord-safe`、`h-chat`など他Profileは自動Captureしない。必要な意図だけ明示転送する。

### 4.2 夜レビュー

- 21:00に月次セッション`Supervisor Console — YYYY-MM`へ保存する。
- 現行Hermes `SessionDB`はnamed sessionを作成できるが、nesquena WebUIのpinはWebUI sidecar所有である。MVPではWebUIをforkせず、月次Console初回の`Human Actions`でpinを一度依頼する。将来、公開された安全なpin APIが利用可能になった時だけ自動化を再検討する。
- 10分以内で読める量にする。
- 判断事項は最大10件。件数を埋めることを目標にしない。
- 各Decisionへ安定IDを付け、自然言語で一括回答できるようにする。
- 本文は「変わったこと」「判断」「異常」「Human Actions」を中心にする。
- Worker別進捗や全ログは本文へ出さず、WebUI/Kanbanから掘れるようにする。
- 判断がある場合だけDiscordへ件数、最重要一件、WebUIリンクを通知する。
- Discord/Hermes経路障害と緊急警報はntfyへ送る。
- 朝は夜以降に重大変化・期限付き判断が発生した場合だけ短い補足を作る。

### 4.3 人間作業

- 人間用Agent Profileや人間用Kanbanを作らない。
- 一時的な人間作業は夜ブリーフの`Human Actions`へ出す。
- 長期追跡が必要な人間作業だけVaultへ置く。
- 人間がWebUIで完了を報告すると、Supervisorが関連cardを再評価する。

## 5. Capture契約

### 5.1 正本

- 会話原文: `~/.hermes/state.db`
- 抽出意図: `~/.hermes/kanban.db`の`triage` card
- 長期の目的・判断: Obsidian Vault

### 5.2 Capture card

各cardは最低限、以下を保持する。

- source profile
- source session ID
- source message ID
- source timestamp
- 原文を改変しない参照または必要最小限の引用
- Supervisorの解釈
- intent temperature
- confidence
- 関連する既存goal/card
- supersedes / retracts関係
- idempotency key

idempotency keyは少なくとも`profile + session_id + message_id + extractor_version`から導出する。

### 5.3 intent temperature

1. `observe`: 関心・仮説として保持。実行しない。
2. `research`: 調査・比較・論点整理まで自動前進できる。
3. `build`: isolated実装・テスト・dry-run・Verifier確認まで自動前進できる。

不確実な場合は低い段階へ置く。実環境適用はtemperatureにかかわらず人間ゲートを通す。

### 5.4 訂正・撤回

- 原文を上書きしない。
- 元cardへのcomment/eventと新しいCaptureで訂正関係を残す。
- 撤回されたcardはdispatchしない。
- すでに動いている場合、影響範囲を評価し、不要なら停止する。
- 曖昧な訂正を推測で既存cardへ結び付けない。

## 6. Supervisor契約

Supervisorは実装を行わない。

責務:

- 新規Captureの重複・訂正・撤回・矛盾を処理する。
- Captureをactive goalへ接続する。
- 上位目的と現在のWIPを守り、新しい思いつきで無条件に中断しない。
- 作業をResearcher / Builder / Verifierへ分解する。
- permission・risk・workspace・skill・完了条件・rollbackをcardへ記録する。
- budget内でdispatchする。
- 判断待ちをDecision Queueへ送る。
- 前回計画との差分を構造化ログへ残す。

優先順位:

1. 安全・期限・データ損失
2. active goalを止めるblocker
3. 着手済み仕事の完遂
4. 反復・明示強調された関心
5. 複数目的を解放する高レバレッジ基盤
6. 低コストで不確実性を大きく減らす調査
7. 通常の改善・探索
8. いつかやりたい関心

同じ層でだけ、効果・コスト・可逆性・鮮度を比較する。Stage 0では固定したprimary goalが、安全・期限を除く新規goalより優先される。

## 7. Agent Profileと権限

### Supervisor

- read: default会話差分、Kanban、allowed Vault、関連repo、サービス索引
- write: Kanbanの形成・assign・comment・schedule、構造化監査ログ
- 禁止: 実装、実環境適用、権限拡大の自己承認

Supervisor管理cardの運用上の所有境界は、明示pinされた専用Kanban boardとする。board内では完全一致の`created_by`を誤操作防止の識別子として使うが、これは認証情報ではない。同じUNIX userとしてHermes homeへwriteできる人が公開CLI metadataまたはDBを意図的に偽装する脅威はMVP外とし、人間の無関係なcardは別boardへ置く。停止処理はglobal current boardへ依存しない。

### Researcher

- read-only調査
- Web、Vault（`05-Private/`除外）、repo、サービス状態
- 外部書き込み・ファイル編集をしない

### Builder

- `scratch`またはproject-bound isolated worktreeだけを編集
- テスト、lint、build、dry-runまで
- main worktree、実環境、NAS共有資源へ直接writeしない
- commit / pushしない

### Verifier

- 成果、diff、テスト、受け入れ条件、rollbackを独立確認
- 不合格理由を構造化して修正cardへ渡す
- 修正を自分で行わない

### Operator（MVP外）

- 承認済み変更だけ実環境へ適用する単一writer
- 資源ごとのrunbookとruntime検証を要求する
- Stage 0では自動起動しない

専門性はProfileではなくcardへ添付するSkillで注入する。

## 8. 自動化境界

### 自動で進めてよい

- read-only調査
- 仕様化・分解
- 一時実験
- scratch/worktree内の編集
- test / lint / build
- Nix dry-run
- read-onlyのruntime確認
- Verifierによる合否判定

### 人間承認が必要

- `nh os switch` / `nh home switch`など実環境適用
- NAS、CalDAV、Paperless、外部APIなどへのwrite
- delete / move / irreversible conversion
- DB migration
- 公開、認証、secret、permission変更
- 継続費用の発生
- Git commit / push / merge / history rewrite
- Vaultの上位目的・ADR・長期判断の確定
- 自動適用runbookへの格上げ

## 9. 状態と完了

- `triage`: 未形成Capture
- `todo/ready/running`: Agent実行状態
- `review`: 適用候補または人間判断待ち
- `blocked`: capability不足、解消不能、重大失敗
- `scheduled`: budgetまたは時期により延期
- `done`: 仕事種別に応じた完了条件を満たす

仕事別の完了:

- 調査: 根拠付き結論をVerifierが確認
- 設計: 未決事項と受け入れ条件が閉じる
- 実装: test合格後も`review`の適用候補
- 実環境変更: 承認、適用、runtime検証まで完了して`done`

## 10. 起動・省トークン要件

- 決定論的watcherを10分ごとに実行する。
- watcherはread-onlyで`state.db`とKanban event/cursorを調べる。
- 変化がなければstdoutを空にし、LLMもcardも起動しない。
- 変化があればidempotentなSupervisor batch cardを一件だけ作る。
- 通常イベントは30分のcooldownで統合する。
- 緊急イベントはcooldownを迂回できる。
- task完了、blocked、Verifier不合格は再計画対象にする。
- 21:00 briefingは変更がある場合だけAgentを呼ぶ。無変更日は決定論的にno-opできる。
- 毎batchで全Vault・全repo・全サービスを走査しない。差分と索引から関連先だけ検索する。
- model/providerはProfileまたはpolicyから差し替え可能にし、Codexへ状態管理を依存させない。

初期budget:

- active goal: 1
- concurrent Worker: 3
- new dispatch: 6 card/day
- Supervisor: 12 run/day
- runtime: 30分/card
- normal retry: 1回
- replan / model escalation: 各1回
- paid Worker: 2 USD/day soft cap

上限到達後は新規仕事を`scheduled`へ送り、進行中の安全な処理は完了させる。

## 11. 失敗回復

1. 同じWorkerで一回だけretryする。
2. Supervisorが原因を分類する。
3. 再分解、別Profile、または上位モデルへ一回だけ昇格する。
4. Verifier不合格は元cardを無条件再実行せず、修正cardを作る。
5. 解決しなければ停止する。
6. 緊急でなければ夜ブリーフへ圧縮する。
7. 人間には原因、試した回復、必要な判断を出す。

## 12. Grill条件

`grill-me`は以下の時だけ候補化する。

- 複数解釈で成果物が大きく変わる
- 上位目的の新設・廃止
- 高コスト・長期・正本変更
- 既存方針との矛盾
- Supervisorが低確信度のまま進めない
- 人間が明示的に要求

Supervisorは勝手にGrillを開始しない。人間が開始を選んだ後、専用セッションで一問ずつ進める。

## 13. 停止・復元

- `Pause dispatch`: Captureと整理を続け、新規Workerを止める。
- `Freeze`: 原文Captureだけ保持し、形成・dispatchを止める。
- `Emergency stop`: 進行中Workerをterminateし、安全な停止状態へ戻す。

停止中も会話原文・Kanban・cursorを削除しない。Resume時は滞留入力を一括実行せず、再評価する。WebUIから操作でき、WebUI障害時はCLIを使えること。

## 14. 監査・保持

各Supervisor batchは以下を構造化して残す。

- 入力message/event ID
- Captureと統合・訂正・撤回関係
- 選択したgoal/card
- 動かさなかった候補と短い理由
- risk / human gate判定
- budget消費
- 前回計画との差分
- confidenceと未解決前提

長期保存:

- 会話原文、Capture、判断、目的変遷、成果、検証

30日後に整理:

- Worker詳細ログ、retry生ログ、一時worktree/sandbox/cache

内部chain-of-thoughtは保存しない。

## 15. 移行試験

### Shadow: 3日

- Capture、triage、goal選択、夜ブリーフを実行する。
- 原則dispatchしない。
- 人間が従来選んだ仕事とSupervisor選択を比較する。

### Limited live: 3日

- Research、仕様化、isolated実装、test、Verifierまで自動dispatchする。
- 実環境適用はしない。
- 新しい細かなAgent作業をVault taskへ追加しない。

### Cutover条件

- 重大Capture漏れがない。
- 誤Captureが可逆で夜レビューを圧迫しない。
- primary goalの選択が概ね納得できる。
- 最低2件が`dispatch → Worker → Verifier → 結果統合`を通る。
- 無承認の実環境変更がゼロ。
- 夜レビューが10分以内。
- 状態確認のためVault task一覧を手動確認しなくてよい。
- 再起動・セッション終了後もKanbanから復元できる。
- 初期budget内で完走する。
- idle / no-change時のLLM呼び出しがゼロ。

すべて満たした場合だけHermesを実行正本へ切り替える。

## 16. MVP範囲外

- 自動Operatorによる実環境適用
- WebUI open/focusトリガー
- 独自Dashboard・専用Decisionボタン
- cross-profile自動Capture
- 専用Capture DB
- Supervisorによる権限の自動拡大
- 動的budget配分の自動採用
- Skill/runbook草案の無承認採用
- n8nまたは外部マルチエージェント基盤への状態正本移行
- Cutover前のVault task全面移行

## 17. 成功の定義

2026-08-21までに、Codexを大量利用できる環境が終了しても以下が成立すること。

- 自然言語入力を失わない。
- idle時にLLM費用を発生させない。
- 一つのprimary goalを、最大3 Agentで安全に前進させられる。
- 強いモデルがなくてもCapture・停止・復元・保留が動く。
- 強いモデルは価値の高い形成と検証へ限定される。
- 人間の通常関与が21:00の10分以内へ収まる。
- 省トークン化のために作ったscript・Skill・runbookが、GitまたはHermes設定履歴から再現できる。
