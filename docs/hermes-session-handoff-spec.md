# Hermes 1-Compact Session Handoff 要件仕様

作成日: 2026-07-26 (JST)
状態: Draft for implementation

## 1. 目的

Codex OAuthの実効context windowが小さい環境で、同じ会話を繰り返し圧縮して判断理由・却下案・未検証事項の区別を劣化させない。

一回目のcontext compressionは安全弁として許容する。二回目のcompressionが必要になる前に、作業状態を構造化checkpointへ外部化し、fresh sessionへhandoffする。

最適化対象はsession寿命ではない。作業の継続性と判断の忠実度を両立すること。

## 2. 適用範囲

MVPの対象:

- Hermes TUIの対話session
- `default` profile
- built-in context compressor
- `compression.in_place = false`
- 自動compressionと手動`/compress`

MVPの対象外:

- delegate subagent
- cron、gateway、WebUIの自動rotation
- Codex app-server native compaction
- Hermes Supervisor / Kanban worker lifecycle
- 複数processから同一sessionを同時resumeする運用

対象外のsurfaceは現行compression動作を維持する。

## 3. 基本方針

1. 一つのlogical task lineageにつき、通常compressionは一回まで許容する。
2. 二回目のcompression要求をhandoff triggerとする。
3. handoff前に構造化checkpointを永続化する。
4. fresh sessionはcheckpointとlive artifactを起点に再開し、旧transcript全体をcontextへ再投入しない。
5. compressionは無効化しない。handoffに失敗した場合の最終安全弁として残す。
6. handoffは承認・権限を拡大しない。
7. checkpointは作業状態の索引であり、実ファイル・Git・test結果・service状態より強い正本ではない。

## 4. 用語

- **segment**: 一つのHermes `session_id`に保存される物理session。
- **compression lineage**: `parent_session_id`で接続され、親の`end_reason = compression`で識別できるsegment列。
- **logical task lineage**: handoff前後を含む、一つの作業目的の系列。
- **checkpoint**: handoff時に生成する構造化された作業状態。
- **fresh session**: 旧transcriptを直接継承せず、checkpointを最小contextとして開始する新segment。

## 5. Trigger契約

### 5.1 Compression count

成功して永続化されたcompression boundaryだけを数える。

- 要約失敗、lock競合、session split失敗は数えない。
- 手動`/compress`と自動compressionを同じ一回として数える。
- delegate childやbranch childは親TUI lineageの回数へ含めない。
- handoff完了後のfresh sessionではcountを0へ戻す。

### 5.2 動作

- count = 0でcompression要求: 現行compressionを実行する。
- count = 1でcompression要求: 通常compressionの代わりにhandoffを試行する。
- handoff失敗: 理由を表示し、現行compressionへfallbackする。
- fallback compression後: sessionを継続できるが、次のturnでhandoff再試行を優先する。

二回目の要求まで待つのはMVPの単純な検出点である。将来は一回目のcompression後、task phase boundaryを検出して早期handoffできる。ただしphase推定だけで作業を中断しない。

## 6. Checkpoint契約

### 6.1 必須field

checkpointは次を保持する。

- schema version
- checkpoint ID
- 作成時刻
- source profile / source session ID
- logical lineage ID
- cwd / Git repo root / branch
- task objective
- constraints and prohibitions
- decisions with rationale
- rejected alternatives with reasons
- verified current state
- changed artifacts
- verification evidence
- unresolved items and assumptions
- next action
- human gates
- stop conditions
- active TODO
- active `/goal`
- running background workへの参照

内部chain-of-thoughtは保存しない。理由は要約された判断根拠として記録し、秘匿された推論過程を要求しない。

### 6.2 Evidence

checkpoint生成後、可能な範囲で決定論的なlive evidenceを付与する。

- Git repoではbranch、`git status --short`、diff対象path
- 実行済みtestのcommand、exit status、timestamp
- background process / delegationの識別子と既知state
- TODOと`/goal`の永続state

checkpoint内の「完了」主張だけを根拠にしない。fresh sessionは関連artifactを再読し、必要なlive stateを再測定する。

### 6.3 保存

保存先:

`~/.hermes/handoffs/<logical-lineage-id>/<checkpoint-id>.json`

要件:

- directory mode `0700`
- file mode `0600`
- 一時fileへのwrite、`fsync`、atomic no-replace publish。同一checkpoint IDの再実行はcanonical payloadが同一の場合だけ既存fileを返し、異なるpayloadを上書きしない
- UTF-8 strict JSON
- bounded size
- duplicate keyとnon-finite numberを拒否
- secret redactionを通す
- checkpoint IDによるidempotency

checkpoint永続化の確認前にsource sessionを終了しない。

## 7. Fresh session契約

handoff成功時は次の順序を守る。

1. checkpointを生成する。
2. checkpointを永続化し、read-back検証する。
3. source sessionを`end_reason = handoff`で終了する。
4. fresh sessionを作成する。
5. fresh sessionへhandoff metadataを設定する。
6. checkpointから最小continuation messageを構築する。
7. TODOと`/goal`を移管する。
8. session context、logging context、TUI active session IDを新IDへ切り替える。
9. 同じuser turnを継続する。

fresh sessionの初期contextは次だけに限定する。

- 新しいsystem prompt
- checkpointの要約ではなく、検証済みcheckpoint本文への参照と必要最小限のcontinuation payload
- handoffを発火させた最新のreal user intent
- 継続に必要なTODO / goal

旧sessionの圧縮summaryやtailをそのまま再投入しない。

DB上はsourceとの追跡可能性を保持する。ただし`end_reason = compression`のchainとは区別し、compression countを引き継がない。handoff metadataには少なくともsource session IDとcheckpoint IDを持つ。

## 8. 承認と実行状態

- `once` approvalは移管しない。
- `session` approvalは移管しない。
- `/yolo`は移管しない。
- profile-wide `always` / allowlist / `approvals.mode`は通常どおり有効。
- irreversible、external write、課金、secret、permission、commit/push、実環境適用のhuman gateはcheckpointへ明記する。
- running background processやdelegationをhandoffだけを理由に停止しない。
- fresh sessionはbackground workを自動で「完了」とみなさず、live stateを確認する。

## 9. Failure契約

handoffはfail-safeにする。

- Phase 1の手動`/handoff-session`失敗: source sessionをliveのまま保ち、失敗を報告して終了する。通常compressionへの自動fallbackは行わない。
- checkpoint生成・redaction・write/read-back失敗: source sessionを終了しない。
- DB boundary失敗: `BEGIN IMMEDIATE`内のsource再読/CAS、destination非存在確認、source end、destination create、continuation message、handoff metadata（および可能なgoal metadata）を全rollbackする。
- TODO / goal移管失敗: sourceをreopenできる限りhandoffをcommitしない。
- UI context切替失敗: DB上のfresh sessionを孤立させずsourceへrollbackする。
- Phase 2の自動handoff失敗: Task 8でのみ通常compressionへfallbackする。fallbackも失敗した場合はprovider hard limitへ進む前に明示的に停止する。

atomicity境界を跨いだ単一ACID transactionは主張しない。checkpoint fileはそれ単体でatomic、SQLiteのsource/destination境界は一つのDB transactionでatomic、TUI/context移行は例外時のcompensating rollbackで戻す。DB commit後からUI switch前のpower lossでは、checkpointから参照可能なrecoverable destinationが残り得る。

失敗messageには、失敗段階、source session ID、checkpoint pathの有無を含める。Phase 2だけはfallback結果も含める。checkpoint本文やsecretをlogへ出さない。

## 10. User experience

通常時は余計な確認を要求しない。

一回目のcompression完了時:

- 「このlineageで一回compressionした」ことを短く表示する。
- 次回はhandoffになることを示す。

handoff成功時:

- old session title
- new session title
- checkpoint ID
- 引き継いだobjective
- 最初に再検証するartifact

を短く表示する。

手動操作:

- `/handoff-session`: countに関係なくcheckpointを作りfresh sessionへ移る。
- `/handoff-status`: compression count、logical lineage、直近checkpoint、次回動作を表示する。
- `/compress`: count = 1なら既定でhandoffへrouteする。通常compressionを強制するescape hatchは明示flagと警告を必要とする。

既存の`/handoff <platform>`とは名称と説明を明確に分ける。

## 11. 観測（Phase 2 Task 8）

content-free telemetryはPhase 1には実装せず、Phase 2 Task 8で次を記録する。

- event: handoff_attempt / handoff_committed / handoff_fallback
- source / destination session ID
- logical lineage ID
- compression count
- checkpoint ID
- duration
- failure stage / class
- fallback compression result

checkpoint本文、user発言、secretはtelemetryへ含めない。

評価指標:

- logical lineageごとのcompression回数
- handoff成功率
- fallback率
- handoff直後の再読・再検証回数
- handoff後にユーザーが訂正した判断・制約の件数
- provider context-limit error件数
- handoffに起因する孤立session / lost TODO / lost goal件数

## 12. Rollout

### Phase 0: Observe

- 現行DBからTUI compression lineage長をread-only集計する。
- handoffは実行しない。
- 既存の二回目警告を維持する。

### Phase 1: Manual checkpoint

- `/handoff-status`と`/handoff-session`を実装する。
- 自動triggerは通知だけにする。
- checkpointとfresh sessionのrollback契約を検証する。
- 手動失敗はsourceをliveに保って報告し、自動compression fallbackやtelemetryは実行しない。

### Phase 2: Automatic second-trigger handoff

- count = 1で次のcompression要求が来た場合に自動handoffする。
- 対象はTUI default profileだけに限定する。
- 失敗時は通常compressionへfallbackする。
- content-free telemetryをTask 8で追加する。

### Phase 3: Expansion review

MVPの実測後にだけ、WebUI / gateway / other profiles / early phase-boundary handoffを検討する。

## 13. Acceptance criteria

- 一回目のcompressionは現行どおり成功する。
- 二回目の要求で通常compressionを重ねず、fresh sessionへhandoffする。
- fresh sessionのcompression countは0である。
- checkpoint欠損・破損時にsource sessionを失わない。
- fresh session作成失敗時にsource sessionへrollbackできる。
- TODOと`/goal`が一度だけ移管される。
- session approvalと`/yolo`が移管されない。
- background workがhandoffだけで停止・完了扱いされない。
- checkpointはmode `0600`、directoryは`0700`である。
- checkpointとtelemetryにsecretが残らない。
- delegate / gateway / cronの既存compression挙動が変わらない。
- 同時handoff要求でcheckpoint・fresh sessionが二重作成されない。
- restart後にcheckpointから手動resumeできる。
- provider context-limit error時も、sourceとcheckpointのどちらかから回復できる。

## 14. 初期判断と見直しtrigger

初期値:

- allowed compression count: 1
- handoff trigger: 二回目のcompression要求
- fallback: 現行compression
- rollout対象: TUI + default profile

見直しtrigger:

- 一回目のcompression直後から品質低下が目立つ。
- handoff頻度が高く、artifact再読コストがcompact損失を上回る。
- handoff後の訂正件数が減らない。
- provider側context windowが拡大する。
- Hermes本体に同等のupstream機能が入る。
- in-place compressionが既定化され、lineageによるcount検出が使えなくなる。

変更時は、観測値、変更理由、期待効果、戻す条件を残す。