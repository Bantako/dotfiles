# Hermes Supervisor MVP Implementation Plan

> **For Hermes:** Use `subagent-driven-development` to implement this plan task-by-task. Do not commit, push, apply Home Manager, or modify live Hermes profiles without explicit user approval.

**Goal:** Build a recoverable, event-driven Supervisor loop that captures `default` WebUI intentions into Hermes Kanban, advances one primary goal through permission-separated Agents, and reaches a low-token steady state by 2026-08-21.

**Architecture:** A Python stdlib adapter reads `state.db` and `kanban.db` read-only, stores its own cursor/control state under `~/.local/state/hermes-supervisor/`, and performs all Kanban writes through the public `hermes kanban` CLI. Home Manager installs systemd user services/timers. Hermes profiles provide role and permission boundaries; Skills provide domain expertise. The first vertical slice runs in Shadow mode before any Worker dispatch.

**Tech Stack:** Python 3 stdlib (`sqlite3`, `json`, `subprocess`, `pathlib`, `dataclasses`, `unittest`), Hermes Agent CLI/Kanban/Profile/Cron primitives, Nix/Home Manager, systemd user services, Discord and ntfy fallback.

**Requirements:** `docs/hermes-supervisor-system-spec.md`

---

## Constraints

- Do not read `05-Private/`.
- Never write directly to Hermes SQLite databases.
- Never print or inspect `.env`, `auth.json`, SOPS values, or credential files.
- Use a temporary SQLite fixture for tests.
- Keep Shadow mode as the default until its acceptance gate passes.
- Stage 0 has one fixed primary goal. Parallelism occurs only inside that goal.
- Builder work happens only in `scratch` or project-bound worktrees.
- Do not commit/push or run `nh home switch` unless the user separately approves.
- Before any Home Manager application, run `nh home switch --dry` (use `--impure` if absolute-path evaluation requires it).

## Proposed Files

- Create: `tools/hermes_supervisor.py`
- Create: `tools/test_hermes_supervisor.py`
- Create: `home/modules/ai/hermes-supervisor.nix`
- Create: `home/modules/ai/hermes-supervisor/policy.json`
- Create: `home/modules/ai/hermes-supervisor/prompts/supervisor.md`
- Create: `home/modules/ai/hermes-supervisor/prompts/researcher.md`
- Create: `home/modules/ai/hermes-supervisor/prompts/builder.md`
- Create: `home/modules/ai/hermes-supervisor/prompts/verifier.md`
- Create: `home/modules/ai/hermes-supervisor/prompts/briefing.md`
- Modify: `home/home.nix`
- Modify: `docs/hermes-supervisor-system-spec.md` only when implementation findings require a documented requirement correction

## Runtime Paths

- Policy deployed to: `~/.config/hermes-supervisor/policy.json`
- Prompts deployed to: `~/.config/hermes-supervisor/prompts/`
- Mutable cursor/control state: `~/.local/state/hermes-supervisor/state.json`
- Structured run records: `~/.local/state/hermes-supervisor/runs/YYYY-MM-DD.jsonl`
- Read-only source DB: `~/.hermes/state.db`
- Read-only Kanban DB: `~/.hermes/kanban.db`

## CLI Contract

`tools/hermes_supervisor.py` exposes:

- `validate-policy`
- `watch --mode shadow|limited|eco`
- `brief --date YYYY-MM-DD`
- `control status|pause|freeze|emergency-stop|resume`
- `gc --older-than 30d`
- `acceptance-report --phase shadow|limited`
- `bootstrap-profiles --dry-run`

All mutating subcommands support `--dry-run`. `watch` defaults to Shadow unless the persisted mode explicitly says otherwise.

---

### Task 1: Add the versioned policy schema

**Objective:** Make every provisional limit explicit, validated, and changeable without editing code.

**Files:**
- Create: `home/modules/ai/hermes-supervisor/policy.json`
- Create: `tools/hermes_supervisor.py`
- Create: `tools/test_hermes_supervisor.py`

**Step 1: Write failing policy tests**

Cover:

- Stage 0 requires `active_goal_limit == 1`.
- `worker_concurrency == 3`.
- `daily_dispatch_limit == 6`.
- `daily_supervisor_limit == 12`.
- `task_runtime_seconds == 1800`.
- `normal_retry_limit == 1`.
- `replan_limit == 1`.
- `model_escalation_limit == 1`.
- `paid_worker_soft_limit_usd == 2`.
- watcher interval is 600 seconds and normal batch cooldown is 1800 seconds.
- briefing time is `21:00` in `Asia/Tokyo`.
- unknown keys and invalid negative limits fail closed.
- `05-Private/` appears in the denied path list.

**Step 2: Verify RED**

Run:

```bash
python3 tools/test_hermes_supervisor.py -v
```

Expected: FAIL because policy loading and validation do not exist.

**Step 3: Implement minimal schema loading**

Use immutable dataclasses. Reject unknown/missing keys. Keep these sections:

- `stage`
- `scheduling`
- `budget`
- `capture`
- `permissions`
- `briefing`
- `retention`
- `models`

Model entries are aliases (`strong_supervisor`, `strong_verifier`, `cheap_worker`), not provider-specific code paths.

**Step 4: Verify GREEN**

Run the same unittest command. Expected: all policy tests pass.

**Step 5: Validate CLI**

Run:

```bash
python3 tools/hermes_supervisor.py validate-policy \
  --policy home/modules/ai/hermes-supervisor/policy.json
```

Expected: exit 0 and a one-line summary containing `stage=bootstrap active_goals=1` without secret values.

**Checkpoint commit if requested:** `feat(hermes): add supervisor policy schema`

---

### Task 2: Build deterministic read-only change detection

**Objective:** Detect new default-profile messages and relevant Kanban events without invoking an LLM when nothing changed.

**Files:**
- Modify: `tools/hermes_supervisor.py`
- Modify: `tools/test_hermes_supervisor.py`

**Step 1: Add temporary DB fixtures**

Create test schemas matching the observed columns:

- `state.db.messages`: `id`, `session_id`, `role`, `content`, `timestamp`, `active`, `compacted`
- `state.db.sessions`: `id`, `source`, `title`, `archived`, `ended_at`
- `kanban.db.task_events`: `id`, `task_id`, `run_id`, `kind`, `payload`, `created_at`
- `kanban.db.tasks`: fields needed to classify `blocked`, `done`, `review`, `triage`

Do not copy the live databases into tests.

**Step 2: Write failing detector tests**

Cover:

- only messages after `last_message_id` are returned;
- assistant/tool messages are ignored for Capture;
- archived sessions are ignored;
- only the configured `default` DB is read;
- Kanban `completed`, `blocked`, and verifier-failure events are detected;
- repeated poll with unchanged cursors returns an empty change set;
- SQLite is opened with URI `mode=ro`;
- a missing or schema-incompatible DB fails closed and does not advance cursors.

**Step 3: Verify RED**

Run unittest. Expected: detector tests fail.

**Step 4: Implement `ChangeSet` and DB readers**

The reader returns IDs and minimal metadata. It must not load unrelated historical message bodies. Add `schema_version`/column checks with actionable errors.

**Step 5: Verify GREEN and no-op output**

Run:

```bash
python3 tools/test_hermes_supervisor.py -v
```

Then run `watch --dry-run` against an unchanged fixture. Expected: exit 0 and empty stdout.

**Checkpoint commit if requested:** `feat(hermes): detect supervisor input changes`

---

### Task 3: Add atomic cursor and control state

**Objective:** Survive reboot or process interruption without losing or duplicating Capture.

**Files:**
- Modify: `tools/hermes_supervisor.py`
- Modify: `tools/test_hermes_supervisor.py`

**Step 1: Write failing state tests**

Cover:

- initial mode is `shadow`;
- cursor file is created with mode `0600`;
- writes use temp-file + `fsync` + atomic replace;
- `pause` retains Capture cursors but prevents dispatch;
- `freeze` records observed message IDs but does not form cards;
- `emergency-stop` records the stop request before process termination commands;
- `resume` does not clear backlog or budget history;
- corrupt state is quarantined and defaults to `freeze`, not `limited`.

**Step 2: Implement state transitions**

Store:

- `mode`
- `control_state`
- `last_message_id`
- `last_event_id`
- `last_supervisor_enqueued_at`
- daily budget counters
- pending change IDs
- last accepted primary goal ID
- extractor version

Use file locking to prevent overlapping timer runs.

**Step 3: Verify**

Run unittest and two concurrent `watch --dry-run` processes against fixtures. Expected: only one obtains the lock; neither corrupts state.

**Checkpoint commit if requested:** `feat(hermes): persist supervisor cursor and controls`

---

### Task 4: Convert changes into idempotent Capture cards

**Objective:** Create one reversible `triage` projection per source intent while preserving source linkage.

**Files:**
- Modify: `tools/hermes_supervisor.py`
- Modify: `tools/test_hermes_supervisor.py`

**Step 1: Write failing planner tests**

Cover:

- idempotency key is derived from `default`, session ID, message ID, and extractor version;
- the same source never produces a second non-archived card;
- source IDs and timestamp are included in the body;
- raw source text is not rewritten;
- oversized content is referenced and minimally excerpted;
- likely correction/retraction creates a candidate relation but does not guess a target when ambiguous;
- Shadow mode creates `--triage` cards with no assignee/dispatch;
- shell arguments are passed as an argv list, never interpolated into a shell string.

**Step 2: Implement `HermesKanbanClient`**

Use only public CLI calls such as:

```text
hermes kanban create TITLE --body BODY --triage \
  --idempotency-key KEY --created-by supervisor-capture --json
hermes kanban comment TASK_ID TEXT --author supervisor
```

Inject the executable path and runner in tests. Parse JSON strictly and treat malformed output as failure.

**Step 3: Make cursor advancement transactional at the adapter level**

Do not advance a source message past a failed card creation. Idempotency makes retry safe after a crash between CLI success and cursor write.

**Step 4: Verify**

Use a fake `hermes` binary fixture that records argv and returns stable task IDs. Run the watcher twice. Expected: one create command and no duplicate.

**Checkpoint commit if requested:** `feat(hermes): project conversation intents into triage`

---

### Task 5: Add budget and one-primary-goal dispatch gates

**Objective:** Ensure Stage 0 cannot silently expand to several top-level goals or unbounded work.

**Files:**
- Modify: `tools/hermes_supervisor.py`
- Modify: `tools/test_hermes_supervisor.py`

**Step 1: Write failing gate tests**

Cover:

- only one primary goal can be active in Bootstrap;
- child cards inside that goal may use three Worker slots;
- unrelated new goals remain `triage/scheduled`;
- safety and data-loss events may preempt the primary goal;
- daily Supervisor run 13 is not enqueued;
- daily dispatch 7 is scheduled;
- paid Worker over the soft cap is scheduled;
- a running safe card is not killed merely because the date/budget boundary is reached;
- budget reset follows `Asia/Tokyo` date.

**Step 2: Implement the gate as a pure decision function**

Return `allow`, `schedule`, or `needs_human` plus a stable reason code. Keep policy separate from CLI side effects.

**Step 3: Verify**

Run unittest. Generate a dry-run decision report and confirm it includes reason codes without chain-of-thought.

**Checkpoint commit if requested:** `feat(hermes): enforce supervisor bootstrap budgets`

---

### Task 6: Create role prompts and bootstrap four Profiles

**Objective:** Establish permission-separated Supervisor, Researcher, Builder, and Verifier identities without copying domain specialization into Profiles.

**Files:**
- Create: `home/modules/ai/hermes-supervisor/prompts/supervisor.md`
- Create: `home/modules/ai/hermes-supervisor/prompts/researcher.md`
- Create: `home/modules/ai/hermes-supervisor/prompts/builder.md`
- Create: `home/modules/ai/hermes-supervisor/prompts/verifier.md`
- Modify: `tools/hermes_supervisor.py`
- Modify: `tools/test_hermes_supervisor.py`

**Step 1: Write prompt contract tests**

Assert each prompt contains its role, write boundary, completion contract, and `05-Private/` denial where applicable. Assert:

- Supervisor says it does not implement;
- Researcher says read-only;
- Builder requires scratch/worktree and prohibits live apply/commit/push;
- Verifier prohibits self-fixing and requires evidence.

**Step 2: Implement `bootstrap-profiles --dry-run`**

Plan these public operations:

```text
hermes profile create supervisor --clone-from default --description ...
hermes profile create researcher --clone-from default --description ...
hermes profile create builder --clone-from default --description ...
hermes profile create verifier --clone-from default --description ...
```

Do not create profiles during tests. Detect existing profiles and be idempotent.

**Step 3: Configure and verify tools with profile aliases**

After explicit approval to mutate live Profiles, use the generated aliases (`hermes-supervisor`, `hermes-researcher`, etc.) and public commands:

```text
hermes-ROLE tools list
hermes-ROLE tools enable ...
hermes-ROLE tools disable ...
hermes-ROLE config set model MODEL
hermes-ROLE config check
```

Before executing, consult current Hermes documentation for exact toolset names. Do not derive permission behavior from prompt text alone. Capture `hermes-ROLE tools list` output as verification evidence.

**Step 4: Install role prompts safely**

Copy/version prompts from the deployed config tree into Profile `SOUL.md` only after showing the diff. Do not overwrite unrelated Profile state.

**Step 5: Verify**

- Researcher cannot invoke write toolsets.
- Builder can edit only inside a test scratch/worktree task.
- Verifier can run read-only tests/inspection but cannot patch files.
- Supervisor can operate Kanban but not project files.

**Checkpoint commit if requested:** `feat(hermes): define permission-separated agent roles`

---

### Task 7: Add Supervisor batch enqueueing

**Objective:** Enqueue at most one Supervisor card for accumulated changes after the 30-minute cooldown.

**Files:**
- Modify: `tools/hermes_supervisor.py`
- Modify: `tools/test_hermes_supervisor.py`
- Create: `home/modules/ai/hermes-supervisor/prompts/supervisor.md` additions as needed

**Step 1: Write failing batch tests**

Cover:

- no changes emits no stdout and invokes no Hermes CLI;
- changes inside the cooldown accumulate without enqueue;
- after cooldown, one card contains source/event IDs;
- repeated execution uses one idempotency key per batch window;
- emergency events bypass cooldown;
- Supervisor card uses assignee `supervisor`, `--max-runtime 30m`, and one retry under the correct Hermes `--max-retries` semantics;
- Shadow mode produces an analysis result but no child dispatch;
- Limited mode may dispatch only allowed temperatures and workspaces.

**Step 2: Implement batch card creation**

Use `hermes kanban create ... --json`. Put source IDs in structured body/metadata and keep a short title. Attach required orchestration Skills explicitly.

**Step 3: Verify against an isolated Kanban board/profile**

Do not use the live default board for the first integration test. Create or bind a disposable test project/board, enqueue one fixture batch, run a bounded dispatch, and verify task/run/event records through `hermes kanban show --json`.

**Checkpoint commit if requested:** `feat(hermes): enqueue change-driven supervisor batches`

---

### Task 8: Install watcher and maintenance systemd timers through Home Manager

**Objective:** Run low-cost polling and retention declaratively without a custom always-on daemon.

**Files:**
- Create: `home/modules/ai/hermes-supervisor.nix`
- Modify: `home/home.nix`
- Modify: `tools/hermes_supervisor.py`

**Step 1: Add a Nix evaluation test target**

The module must:

- package/install `tools/hermes_supervisor.py` with Python 3;
- deploy policy and prompts under `~/.config/hermes-supervisor/`;
- define `hermes-supervisor-watch.service` as oneshot;
- define `hermes-supervisor-watch.timer` with a 10-minute calendar and `Persistent=true`;
- prevent overlap;
- define a daily GC timer;
- set a restrictive umask;
- set explicit PATH entries for Hermes, Python, and SQLite needs;
- route failures through the existing `hermes-failure-notify@%N.service` pattern;
- not embed secrets or provider keys.

**Step 2: Import the module**

Add `./modules/ai/hermes-supervisor.nix` near the existing Hermes imports in `home/home.nix`.

**Step 3: Format and dry-evaluate**

Run:

```bash
nixfmt home/modules/ai/hermes-supervisor.nix home/home.nix
nh home switch --dry
```

If evaluation reports an absolute-path restriction, rerun with the repo's required `--impure` form. Expected: dry-run succeeds; no live service is started.

**Step 4: Inspect generated units without applying**

Use Home Manager/Nix build output to verify command paths, timers, umask, and failure dependency.

**Checkpoint commit if requested:** `feat(hermes): schedule supervisor change detection`

---

### Task 9: Build the monthly Supervisor Console and 21:00 briefing

**Objective:** Produce a bounded nightly review in WebUI, with Discord only when decisions exist.

**Files:**
- Modify: `tools/hermes_supervisor.py`
- Modify: `tools/test_hermes_supervisor.py`
- Modify: `home/modules/ai/hermes-supervisor.nix`
- Modify: `home/modules/ai/hermes-supervisor/prompts/briefing.md`

**Step 1: Write failing briefing tests**

Cover:

- title is `Supervisor Console — YYYY-MM`;
- sections are changed outcomes, Decisions, anomalies, Human Actions;
- Decision IDs are stable and unique;
- at most 10 Decisions are included;
- no Worker-by-Worker activity dump;
- no-change/no-decision day can be a deterministic no-op;
- Discord payload is empty when there are no Decisions;
- Discord payload contains only count, most important Decision, and WebUI link;
- nightly adapter rejects emergency delivery; the actual emergency detection/ntfy route is implemented with the Emergency stop transaction in Task 10;
- user replies such as `D1 適用 / D2 B / 残りは推奨` are parsed, while dangerous Decisions require explicit individual answers.

**Step 2: Implement briefing projection**

Read task/result/event state and Supervisor run logs. Do not regenerate history from all messages. Persist the generated briefing and Decision mapping before delivery.

**Step 3: Connect to WebUI-supported session/cron delivery**

Verify the current nesquena WebUI/Hermes cron session attachment behavior in an isolated test session. If direct injection into a named monthly session is unsupported, use the smallest adapter that creates or resumes the monthly Hermes session; do not fork WebUI for MVP.

**Step 4: Add the 21:00 timer**

Use an `Asia/Tokyo` systemd timer or Hermes cron with a self-contained prompt. Ensure this TUI's local-only delivery limitation is irrelevant: the target is the WebUI session, while Discord receives only the fallback summary.

**Step 5: Verify end to end**

Create fixture cards for one completion, one application candidate, one Decision, and one Human Action. Generate the brief and verify:

- full brief appears once in the test Console;
- one short Discord test payload is produced;
- rerun is idempotent;
- no secret/log body is included.

**Checkpoint commit if requested:** `feat(hermes): add nightly supervisor briefing`

---

### Task 10: Implement Pause, Freeze, Emergency stop, and Resume

**Objective:** Make the system safely controllable from WebUI and CLI.

**Files:**
- Modify: `tools/hermes_supervisor.py`
- Modify: `tools/test_hermes_supervisor.py`
- Modify: `home/modules/ai/hermes-supervisor.nix`
- Modify: `home/modules/ai/hermes-supervisor/prompts/supervisor.md`

**Step 1: Write failing control integration tests**

Cover:

- Pause blocks new Worker dispatch but continues Capture/Supervisor organization;
- Freeze stores source cursors/pending IDs but creates no new cards;
- Emergency stop enumerates only Supervisor-managed running tasks and requests termination/reclaim through public Hermes commands;
- Emergency stop emits one bounded ntfy alert through a route distinct from nightly Discord delivery;
- unrelated user Kanban work is untouched;
- Resume schedules a re-evaluation batch rather than immediately dispatching the whole backlog;
- every transition writes a structured audit record.

**Step 2: Implement public-CLI control operations**

Use `hermes kanban list --json`, `block`, `schedule`, `reclaim`, or other documented commands. Confirm exact termination/reclaim semantics against current Hermes docs before touching live tasks. Couple the emergency audit result to a dedicated ntfy oneshot/adapter; never route emergency payloads through the nightly Discord briefing.

**Step 3: Expose natural-language control through Supervisor prompt**

Map unambiguous commands to the adapter. Ambiguous “止めて” asks which level unless an active emergency makes fail-closed Emergency stop appropriate.

**Step 4: Verify on disposable tasks**

Start bounded sleep tasks in a disposable board, exercise all controls, and confirm unrelated tasks survive.

**Checkpoint commit if requested:** `feat(hermes): add supervisor safety controls`

---

### Task 11: Add audit, retention, and eco metrics

**Objective:** Preserve decisions while making token/cost reduction measurable.

**Files:**
- Modify: `tools/hermes_supervisor.py`
- Modify: `tools/test_hermes_supervisor.py`
- Modify: `home/modules/ai/hermes-supervisor.nix`

**Step 1: Write failing audit tests**

Each JSONL run record contains:

- input message/event IDs;
- Capture relations;
- selected primary goal/card;
- skipped candidate reason codes;
- risk/gate decision;
- budget counters;
- changed plan fields;
- confidence and unresolved assumptions;
- LLM/API call count, token counts, estimated/actual cost where available;
- no chain-of-thought or message reasoning fields.

**Step 2: Implement retention**

- archive completed cards after 30 days via public Kanban GC/archive operations;
- delete only Supervisor-owned detailed logs/worktrees/sandboxes older than 30 days;
- retain conversation, Capture, Decision, outcome, and verification records;
- `gc --dry-run` lists exact candidates;
- paths outside configured roots are rejected.

**Step 3: Implement eco report metrics**

Report:

- idle polls and LLM calls caused by them;
- batches per source change;
- strong vs cheap model invocations;
- token/cost per accepted result;
- retries/escalations;
- human corrections;
- review duration entered by the user or estimated from reply timestamps;
- number of procedures converted to deterministic script/Skill/runbook.

**Step 4: Verify**

Run retention against temporary directories and a fixture DB. Expected: only eligible Supervisor-owned artifacts are selected.

**Checkpoint commit if requested:** `feat(hermes): measure and retain supervisor runs`

---

### Task 12: Run the 3-day Shadow phase

**Objective:** Validate Capture and planning without autonomous Worker execution.

**Files:**
- Runtime state only under `~/.local/state/hermes-supervisor/`
- Update: `docs/hermes-supervisor-system-spec.md` only for accepted requirement corrections

**Prerequisite:** Explicit user approval to apply Home Manager and create live Profiles.

**Step 1: Apply declarative config safely**

Run:

```bash
nh home switch --dry
nh home switch
```

Use the repo-required `--impure` variant if needed. Verify timers before enabling live mode.

**Step 2: Initialize Shadow**

- capture the initial high-water marks so historical conversations are not bulk-imported accidentally;
- explicitly select the one primary goal;
- set control state to `resume`, mode `shadow`;
- start the watcher timer;
- create/pin the monthly Supervisor Console.

**Step 3: Observe for three days**

Collect:

- missed important intentions;
- false captures;
- correction/retraction behavior;
- proposed primary work vs human choice;
- no-op poll count;
- Supervisor call count and cost;
- nightly review duration;
- duplicate card count.

**Step 4: Produce Shadow acceptance report**

Run:

```bash
hermes-supervisor acceptance-report --phase shadow
```

Do not advance if:

- any major Capture is missed;
- no-op causes an LLM call;
- duplicate non-archived cards exist;
- review exceeds 10 minutes repeatedly;
- the primary goal selection is unacceptable.

**Checkpoint commit if requested:** `test(hermes): record supervisor shadow acceptance`

---

### Task 13: Run the 3-day Limited live phase

**Objective:** Exercise the complete low-risk path through independent verification.

**Prerequisite:** Shadow gate passes and user explicitly approves mode transition.

**Step 1: Enable only low-risk dispatch**

Permit:

- Researcher read-only work;
- specification/decomposition;
- Builder scratch/project worktree changes;
- tests, builds, Nix dry-runs;
- Verifier review.

Continue blocking live apply, external write, commit, and push.

**Step 2: Execute at least two vertical slices**

Each slice must produce:

- source Capture ID;
- Supervisor spec and acceptance criteria;
- Worker evidence;
- Verifier verdict;
- result integration;
- application candidate or completed research outcome;
- rollback note where relevant.

**Step 3: Test recovery**

During a controlled low-risk task:

- restart the watcher service;
- close the originating WebUI session;
- verify Kanban/state recovery;
- test Pause and Resume;
- test one bounded Worker failure and recovery path.

**Step 4: Produce Limited acceptance report**

All specification Cutover conditions must pass. Any unauthorized write is an automatic failure.

**Checkpoint commit if requested:** `test(hermes): verify limited supervisor operation`

---

### Task 14: Enter Eco steady state before 2026-08-21

**Objective:** Make the system useful after abundant Codex access ends.

**Files:**
- Modify policy/prompts/scripts only where measured Shadow/Limited results justify a change
- Add or update Skills/runbooks for repeated successful procedures

**Step 1: Classify every repeated model action**

For each recurring action, choose:

1. deterministic script/state machine;
2. cached lookup/artifact reuse;
3. Skill/runbook with a cheap Worker;
4. strong-model-only exception.

Do not keep a recurring strong-model call merely because it already works.

**Step 2: Pin Eco model aliases**

- cheap Worker is default;
- strong Supervisor is invoked only for changed batches needing semantic integration;
- strong Verifier is used for high-risk or ambiguous outcomes;
- unavailable strong provider causes safe scheduling/review, not state loss.

**Step 3: Run an idle proof**

Observe a 24-hour no-change window or an equivalent accelerated fixture/integration test. Expected: watcher polls occur and Supervisor-related LLM call count remains zero.

**Step 4: Run the same evaluation set with reduced resources**

Replay anonymized/fixture Capture and task cases gathered during Bootstrap. Compare Capture decisions, goal routing, Verifier outcomes, cost, and human corrections.

**Step 5: Record the transition decision**

Document:

- model allocation before/after;
- measured cost/token reduction;
- remaining strong-model exceptions;
- accepted quality regressions, if any;
- triggers for returning temporarily to Bootstrap mode.

Do not increase active goals yet. Expansion to two goals is a separate post-MVP Decision after stable Eco operation.

**Checkpoint commit if requested:** `feat(hermes): enter supervisor eco mode`

---

## Final Verification Checklist

### Functional

- [ ] default WebUI messages become idempotent `triage` cards.
- [ ] corrections/retractions remain traceable and reversible.
- [ ] one primary goal is enforced.
- [ ] three internal Workers can run without shared-write conflict.
- [ ] Supervisor cannot self-approve Verifier failures.
- [ ] implementation candidates do not appear as live-complete.
- [ ] monthly Console and Decision IDs work.
- [ ] Discord only notifies when Decisions exist.

### Safety

- [ ] no direct SQLite writes.
- [ ] no secrets in repo, logs, card bodies, or notifications.
- [ ] `05-Private/` remains inaccessible.
- [ ] Builder cannot edit main/live resources.
- [ ] live apply, external writes, commit, and push require a human gate.
- [ ] Pause, Freeze, Emergency stop, and Resume are verified.
- [ ] state corruption fails closed.

### Energy / Cost

- [ ] no-change poll invokes no LLM.
- [ ] duplicate source change invokes no duplicate Supervisor task.
- [ ] policy caps are enforced.
- [ ] cheap Worker is default.
- [ ] strong-model use has a reason code.
- [ ] Limited live fits the initial daily budget.
- [ ] Codex unavailability does not lose Capture or execution state.

### Repository

- [ ] `python3 tools/test_hermes_supervisor.py -v` passes.
- [ ] `nixfmt` produces no diff on touched Nix files.
- [ ] `nh home switch --dry` passes.
- [ ] only intended files are changed.
- [ ] existing staged Grimmory/Szurubooru work remains untouched.
- [ ] no commit or push occurs without explicit approval.

## Proposed Semantic Commit Boundaries

Only if the user explicitly asks to commit:

1. `docs(hermes): define asynchronous supervisor system`
2. `feat(hermes): add supervisor capture and policy engine`
3. `feat(hermes): add permission-separated worker profiles`
4. `feat(hermes): schedule supervisor and nightly briefing`
5. `test(hermes): verify supervisor shadow and limited modes`
6. `feat(hermes): enter low-token supervisor operation`
