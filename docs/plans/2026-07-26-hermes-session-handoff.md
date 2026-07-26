# Hermes 1-Compact Session Handoff Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 一回のcontext compression後、二回目のcompression要求を構造化checkpoint付きfresh session handoffへ置き換える。

**Architecture:** Hermes coreへhandoff state machineを追加し、`SessionDB`がcheckpoint metadataと`end_reason=handoff`の原子的なSQLite session境界を管理する。checkpoint file、SQLite boundary、TUI/contextは単一cross-resource ACID transactionではない。checkpointはatomic publish、DBはsource end・destination create・continuation・metadataを一transaction、TUI/contextはcompensating rollbackとし、DB commit後のpower lossではcheckpointから辿れるrecoverable destinationを許容する。Phase 1ではTUIの手動`/handoff-status`と`/handoff-session`だけを実装し、rollback・permission・TODO/goal移管を実証する。Phase 2で既存compression entrypointから同じstate machineを呼び、対象surfaceをTUI `default` profileへ限定する。

**Tech Stack:** Python 3.12、SQLite、Hermes TUI、Nix `pkgs.applyPatches`、unittest/pytest、Home Manager

**Pinned upstream:** `NousResearch/hermes-agent@2841a9cbca17915c5b983131fa18e3f21bd3983d`

**Requirement:** [`docs/hermes-session-handoff-spec.md`](../hermes-session-handoff-spec.md)

---

## Task 1: Compression lineage countをSessionDBへ追加

**Objective:** delegate/branchを除外し、成功したcompression boundaryだけを数えるread-only APIを作る。

**Files:**

- Modify upstream: `hermes_state.py`
- Test upstream: `tests/test_hermes_state.py`または既存SessionDB compression lineage test file
- Produce patch: `patches/hermes-session-handoff.patch`

**Steps:**

1. root、1回圧縮、複数圧縮、delegate child、branch child、破損cycleのfixtureを作る。
2. `get_compression_count(session_id)`の失敗testを実行する。
3. recursive CTEまたは既存compression edge helperを再利用して最小実装する。
4. countは親の`end_reason='compression'`かつ正規compression childだけを辿ることを確認する。
5. unknown sessionとcycleでfail closedする契約をtestする。
6. 対象testを実行してGREENを確認する。

## Task 2: Handoff checkpoint modelと安全な永続化

**Objective:** bounded strict JSONを`0700/0600`でatomicに保存し、read-back検証できるcomponentを作る。

**Files:**

- Create upstream: `agent/session_handoff.py`
- Test upstream: `tests/agent/test_session_handoff.py`
- Update patch: `patches/hermes-session-handoff.patch`

**Steps:**

1. schema、必須field、size、duplicate key、non-finite、UTF-8、path traversal、symlink、permission、atomic renameの失敗testを書く。
2. `SessionHandoffCheckpoint`のimmutable modelとstrict validatorを作る。
3. `~/.hermes/handoffs/<logical-lineage-id>/`をHermes home helper経由で解決する。
4. directory `0700`、temporary file `0600`、file `fsync`、atomic rename、directory `fsync`を実装する。
5. 同一IDはcanonical payload一致時だけidempotent成功とし、異なるpayloadを上書きしない。read-back時はIDだけでなくstrict schemaとpayload全体の一致を再検証する。
6. `agent.redact.redact_text(..., force=True)`相当の既存redactorを保存境界で適用する。
7. security testと対象testを実行する。

## Task 3: 決定論的evidence collector

**Objective:** LLM checkpointだけに依存せず、cwd・Git・TODO・goal・background参照をboundedに収集する。

**Files:**

- Modify upstream: `agent/session_handoff.py`
- Test upstream: `tests/agent/test_session_handoff.py`

**Steps:**

1. non-Git cwd、dirty repo、巨大status、timeout、missing executableのtestを書く。
2. subprocessはargv配列、bounded stdout/stderr、短いtimeout、secret-redacted resultに限定する。
3. branch、repo root、`git status --short`、変更pathだけを収集する。diff本文はcheckpointへ埋め込まない。
4. `TodoStore`の公開snapshot APIを確認し、なければ副作用のないbounded serializerを追加する。
5. `/goal`は既存goal storeの公開read APIを使う。
6. process/delegationは識別子と既知stateだけを保存し、完了判定しない。
7. collector testをGREENにする。

## Task 4: Handoff session transaction

**Objective:** checkpoint commit後だけsourceを終了し、fresh session作成・TODO/goal移管・context切替を行い、失敗時にsourceへrollbackする。

**Files:**

- Modify upstream: `agent/session_handoff.py`
- Modify upstream: `hermes_state.py`
- Modify upstream: `run_agent.py`
- Test upstream: `tests/agent/test_session_handoff.py`
- Test upstream: SessionDB transaction tests

**Steps:**

1. checkpoint write失敗、source end失敗、destination create失敗、goal移管失敗、TODO移管失敗、context切替失敗のtestを書く。
2. source/destination metadataを定義する。`end_reason='handoff'`を使い、compression child判定へ混入させない。
3. destination `model_config`へcheckpoint ID、source session ID、logical lineage IDをcontent-free metadataとして保存する。
4. checkpoint commit前はDBを変更しない。
5. `BEGIN IMMEDIATE`内でsourceを再読してliveをCASし、destination collisionを拒否してからsource end・destination create・continuation message・handoff metadata・可能なgoal metadataを一括commit/rollbackする。
6. TODOとgoalはcopy成功後にsource側状態をfinalizeし、二重移管を防ぐ。
7. `once`/`session` approvalと`/yolo`を移管しないことをtestする。
8. gateway session context、logging context、environment fallbackを既存compression rotationと同じ順序で切り替える。
9. transaction testをGREENにする。
10. DB commit後のTUI/context切替はcompensating rollbackで戻す。process death時までfilesystem・SQLite・TUIが一つのACID transactionであるとは主張しない。

## Task 5: Minimal continuation payload

**Objective:** 旧transcript全体を再投入せず、checkpoint参照と最新real user intentでfresh contextを構築する。

**Files:**

- Modify upstream: `agent/session_handoff.py`
- Test upstream: `tests/agent/test_session_handoff.py`

**Steps:**

1. synthetic user message、tool result、compression summary、最新real user intentのfixtureを書く。
2. continuation payloadに旧summary/tail/tool outputが混入しないことをREDで確認する。
3. system promptをfreshに再構築する。
4. checkpoint path、objective、次action、再検証対象、最新real user intentだけからrole-alternating message列を作る。
5. secret文字列がpayloadへ残らないことをtestする。
6. empty user intentでは安全なcontinuation markerを使う。

## Task 6: `/handoff-status`と`/handoff-session`

**Objective:** Phase 1の手動handoffをTUIで利用可能にする。

**Files:**

- Modify upstream: `hermes_cli/commands.py`
- Modify upstream: `cli.py`
- Test upstream: CLI command registry tests
- Test upstream: CLI session command tests

**Steps:**

1. command registry、help、autocompleteの失敗testを書く。
2. `/handoff-status`がsession ID、logical lineage、compression count、次回動作、直近checkpointを表示するよう実装する。
3. `/handoff-session`がagent/session stateをhandoff transactionへ渡すよう実装する。
4. agent実行中、画像添付中、handoff lock競合時の扱いを既存session-changing commandに揃える。
5. 既存`/handoff <platform>`と説明・dispatchが衝突しないことをtestする。
6. TUI側のactive session ID、title、history baselineがdestinationへ切り替わることをtestする。
7. Phase 1の失敗はsourceをliveに保って明示報告し、通常compressionへの自動fallbackやtelemetryを実行しない。

## Task 7: Phase 1 integration test

**Objective:** 手動handoffを実session相当のSQLite DBとfilesystemで通す。

**Files:**

- Test upstream: `tests/integration/test_session_handoff.py`

**Steps:**

1. root sessionに会話、TODO、goal、dirty Git fixtureを作る。
2. 一回compressionしたlineageを作る。
3. `/handoff-session`相当を実行する。
4. sourceが`handoff`で終了しdestinationがliveであることを確認する。
5. destinationのcompression countが0であることを確認する。
6. checkpoint permission、schema、evidence、redactionを確認する。
7. destinationのmessagesに旧transcript全体がないことを確認する。
8. process/delegation fixtureが停止・完了扱いされないことを確認する。

## Task 8: 二回目compressionから自動handoff

**Objective:** Phase 1 transactionを再利用し、二回目のcompression要求をhandoffへrouteする。自動compression fallbackとcontent-free telemetryはこのTask 8だけの責務とする。

**Files:**

- Modify upstream: `agent/conversation_compression.py`
- Modify upstream: `run_agent.py`
- Modify upstream: `cli.py`
- Test upstream: `tests/agent/test_conversation_compression.py`
- Test upstream: TUI compression tests

**Steps:**

1. count 0では通常compression、count 1ではhandoff、対象外surfaceでは現行動作、handoff失敗ではcompression fallbackとなるtestを書く。
2. config feature flagを追加し、初期値はoffにする。
3. `platform=tui`、`profile=default`、built-in compressor、`in_place=false`だけを対象にするpredicateを実装する。
4. auto/manualの両entrypointを同じroute関数へ集約する。
5. handoff成功時は通常compressionを呼ばない。
6. handoff失敗時は理由をstatusへ出し、同じ要求で通常compressionを一回だけ実行する。
7. fallbackも失敗した場合はhard-limit前に停止messageを返す。
8. `session:handoff` content-free eventとtelemetryを追加する。

## Task 9: Nix patchとfeature flag

**Objective:** pin済みHermes sourceへ再現可能にpatchを適用し、Phase 1だけを有効化する。

**Files:**

- Create: `patches/hermes-session-handoff.patch`
- Modify: `home/modules/ai/hermes-package.nix`
- Optionally modify: Hermes config migration/defaults in patch

**Steps:**

1. upstream worktreeで変更をpatchとして生成する。
2. patchを既存patch列の末尾へ追加する。
3. Phase 1 commandは利用可能、Phase 2 automatic flagはoffでbuildする。
4. `nix flake check`または対象package buildを実行する。
5. `nh home switch --dry --impure`を実行する。
6. dry-run結果を確認する。実適用は人間の明示承認まで行わない。

## Task 10: 独立review

**Objective:** spec準拠とquality/securityを独立に確認し、Critical/Importantを0へ収束させる。

**Files:**

- Review: `docs/hermes-session-handoff-spec.md`
- Review: `patches/hermes-session-handoff.patch`
- Review: `home/modules/ai/hermes-package.nix`

**Steps:**

1. fresh reviewerへspec compliance reviewを委譲する。
2. Critical/Important指摘を修正し、対象testを再実行する。
3. 別のfresh reviewerへcode quality/security reviewを委譲する。
4. checkpoint persistence、rollback、redaction、approval非移管、concurrencyを重点確認する。
5. Critical/Importantが0になるまで修正と再reviewを行う。

## Task 11: Isolated live probe

**Objective:** 実profileを書き換えず、隔離した`HERMES_HOME`でmanual handoffを実測する。

**Files:**

- Temporary only: isolated Hermes home and fixture repo

**Steps:**

1. temporary `HERMES_HOME`とGit fixtureを作る。
2. patched HermesをTUIまたは同一host control pathで起動する。
3. session作成、一回compression、`/handoff-status`、`/handoff-session`を実行する。
4. DB lineage、checkpoint JSON、permission、destination contextを外側からread-backする。
5. failure injectionでcheckpoint write失敗とdestination create失敗を再現し、source recoveryを確認する。
6. probe artifactを削除し、実profileが変化していないことを確認する。

## Task 12: Phase 2 enablement decision

**Objective:** Phase 1実測を根拠にautomatic second-trigger handoffを有効化するか判断する。

**Steps:**

1. manual handoff成功率、再検証コスト、lost state、訂正件数を評価する。
2. automatic flagをonにする変更案と、manual維持案を比較する。
3. 人間承認後だけ`default` TUI向けautomatic flagを有効にする。
4. `nh home switch --dry --impure`を再実行する。
5. 明示承認後にだけ実環境へ適用する。

---

## Verification commands

upstream test環境では、対象sourceの標準runnerを使う。

```bash
scripts/run_tests.sh tests/agent/test_session_handoff.py -v --tb=short
scripts/run_tests.sh tests/agent/test_conversation_compression.py -v --tb=short
scripts/run_tests.sh tests/test_hermes_state.py -v --tb=short
scripts/run_tests.sh tests/test_cli.py -v --tb=short
```

Nix統合では次を使う。

```bash
nix build .#homeConfigurations.morikawa.activationPackage
nh home switch --dry --impure
```

実適用、commit、pushはこの計画に含めない。