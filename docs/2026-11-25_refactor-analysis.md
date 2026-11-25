# AoC company refactor analysis — 2026-11-25

## Objective

Analyze `pcc-aoc-solver-scala` and propose ground-up refactor plans centered on an
explicit, testable, robust state machine. Compare Paperclip-native designs with
external durable workflow engines such as Temporal, and with custom/git-first
alternatives.

The user's governing constraint:

> The source of truth remains to be the source-code. When there is not evidence/task
> available in the company that a given problem has already been solved the company
> should go through a state-repair phase and check what is already solved. If a
> solution exists and if the result can be successfully submitted then the day/problem
> is considered to be solved.

This means absence of a Paperclip task is **not** evidence that a part is unsolved.
It is a trigger for state repair from the repository and the AoC site.

---

## Authority model

| Concern | Authority |
| --- | --- |
| Canonical fact store | Source repository: committed code plus append-only acceptance receipts/events |
| External acceptance oracle | Authenticated adventofcode.com page |
| Execution coordinator | Paperclip-native, Temporal, or custom worker depending on option |
| Ephemeral projection | Paperclip issues, tasks, documents, comments |
| Untrusted cache | EFS-staged checkout used by an individual agent run |

The LLM/agent never decides the next state. It receives an immutable `WorkOrder`
and emits a signed `ResultEvent`. A deterministic reducer advances state.

---

## Why the current design is fragile

The current workflow is a distributed state machine spread across:

- Paperclip issues/tasks/documents,
- `.aoc/progress.json` in the solution repo,
- the authenticated AoC site,
- disposable EFS-staged checkouts,
- local `flock`,
- agent heartbeats and routines.

No single transaction spans those stores. Known failure modes include:

- all agent heartbeats disabled and a paused `daily-selection` routine with
  `coalesce_if_active`,
- strict title/description/document parsing,
- full 2015+ rewalk in `Controller.select()`,
- separate non-atomic result/disposition/progress/Git writes,
- `Blocked` handler not finishing a routine occurrence,
- local `flock` with a short budget versus 30-minute solver runs,
- stale, empty, or diverged EFS workspaces,
- operator-only recovery and narrow observability,
- Paperclip's ~30-second stranded-issue reconciliation producing repeated
  `issue_continuation_needed` runs when no converged disposition is written.

`DESIGN.md` already identified the unresolved source-of-truth question. The new
constraint resolves it: the repo is canonical, the site is the acceptance oracle,
Paperclip is a projection, and the checkout is a cache.

---

## Shared state machine

This state machine is common to all three options. The engine only coordinates it.

### Core records

```text
PartKey        = year/day/part
Lease          = { lease_id, fence_token, owner, expires_at }
Receipt        = { part_key, commit_sha, answer, site_account,
                   observed_at, page_evidence, submission_id? }
Event          = { event_id, part_key, type, payload, occurred_at,
                   actor, lease_token, idempotency_key }
Command        = { command_id, type, target, payload,
                   fence_token, idempotency_key }
```

The reducer is pure:

```text
reduce(state, event) -> (new_state, [commands])
```

Adapters execute commands idempotently: Git, AoC site, Paperclip API, agent
dispatch. Commands carry fence tokens so stale owners cannot advance state.

### States

| State | Meaning |
| --- | --- |
| `DISCOVERED` | Part exists in the calendar. No evidence evaluated yet. |
| `REPAIR_REQUIRED` | No trustworthy company evidence, missing/corrupt cursor, reimport, drift, lease expiry, or repo/site disagreement. |
| `REPAIRING` | Reconciliation from repo + site is in progress under a lease. |
| `UNSOLVED` | Authenticated site says not accepted; no valid candidate. |
| `CANDIDATE_PRESENT` | Committed solution exists for the part; not yet verified/reproduced. |
| `LOCAL_VERIFIED` | Candidate runs and reproduces exactly one answer. |
| `LEASED` | One executor owns the part; fence token issued. |
| `GATHERING` / `SOLVING` / `PUBLISHING` | Specialist work in progress. |
| `SUBMITTING` | A single idempotent submission attempt is in flight. |
| `UNCERTAIN` | AoC POST outcome unknown. Never blind-retry. Resolve by site query. |
| `ACCEPTED` | Site confirms acceptance and repo receipt exists. Terminal. |
| `REJECTED` | Site explicitly rejected the answer. |
| `RATE_LIMITED` | Retry only after a timer, with bounded attempts. |
| `BLOCKED` | Transient infrastructure failure; bounded retry under lease. |
| `NEEDS_OPERATOR` | Genuine ambiguity, e.g. site accepted but no reproducible repo code. |
| `SUPERSEDED` | A newer attempt/receipt replaced this one; history retained. |

Finale parts skip solve/submit transitions explicitly.

### Key transitions

| From | Event / guard | To | Effects |
| --- | --- | --- | --- |
| any | `EvidenceMissing` or `CursorInvalid` | `REPAIR_REQUIRED` | Acquire repair lease |
| `REPAIR_REQUIRED` | `RepairStarted` | `REPAIRING` | Fresh clone, verify origin HEAD |
| `REPAIRING` | site accepted + candidate answer matches | `ACCEPTED` | Commit receipt, project task done |
| `REPAIRING` | site accepted + no candidate/mismatch | `NEEDS_OPERATOR` | Create blocker, no fabrication |
| `REPAIRING` | candidate exists + site unsolved | `LOCAL_VERIFIED` | Prepare submission |
| `LOCAL_VERIFIED` | `SubmitAttempted` | `SUBMITTING` | One POST with idempotency key |
| `SUBMITTING` | `AcceptedObserved` | `ACCEPTED` | Commit receipt |
| `SUBMITTING` | `UncertainResponse` | `UNCERTAIN` | Park; schedule site query |
| `UNCERTAIN` | site later accepted | `ACCEPTED` | Commit receipt |
| `UNCERTAIN` | site still unsolved | `NEEDS_OPERATOR` | Forbid repeat POST |
| `REJECTED` | bounded retry allowed | `GATHERING` | New attempt, remember rejected answer |
| any active | lease expired | `REPAIR_REQUIRED` | Revoke fence token |
| any | `OperatorResolved` | explicit target | Log operator identity/reason |

### State-repair procedure

State repair is a first-class state, not an operator script.

1. Acquire a lease with a fencing token.
2. Clone the repository fresh; never trust the staged EFS checkout.
3. Enumerate all parts; read receipts/events; ignore Paperclip absence.
4. For each part without trusted evidence:
   - find candidate code from committed history,
   - reproduce the answer with the deterministic runner,
   - query the authenticated AoC page,
   - if site accepted and answer matches: commit receipt, mark `ACCEPTED`,
   - if site unsolved but candidate exists: attempt one idempotent submission,
   - if site accepted but code cannot be found/reproduced: `NEEDS_OPERATOR`.
5. Project results into Paperclip issues idempotently, creating terminal-status
   issues directly so no accidental agent wake occurs.
6. Release the lease only after receipt and projection commits are verified.

### Recommended repo schema

```text
.aoc/
  events/YYYY/D##/part#.jsonl     # append-only canonical events
  receipts/YYYY/D##/part#.json    # acceptance receipts
  state/YYYY/D##/part#.json       # derived snapshot, checksummed
  progress.json                   # derived convenience projection
```

`.aoc/events/` and `.aoc/receipts/` are canonical. `progress.json` and
Paperclip issues are derived projections.

---

## Option 1 — Paperclip-native durable controller

No new workflow engine. Paperclip remains the coordinator, but issues become
projections/leases rather than authority.

### Architecture

- Keep the four capabilities: CTO/controller, Gatherer, Solver, Submitter.
- Only the controller owns transitions.
- Specialists are stateless: they receive a `WorkOrder` and return a signed
  `ResultEvent`.
- Add `aoc_state.py`: pure reducer plus repo ledger/receipts.
- Add `aoc_repair.py`: first-class state-repair command.
- Use Paperclip natives for attention only: blockers, watchdogs, monitors,
  routines, recovery actions, activity log.
- Add a pre-inference gate: no agent wake until repo/site state is reconciled.
- Add a bounded driver: at most one continuation per part per lease window, with
  an explicit converged disposition.

Guard explicitly against Paperclip's durable-continuation loop: repeated
successful runs with `issue_continuation_needed` and no converged disposition
must terminate in `BLOCKED`/`NEEDS_OPERATOR`, not re-wake forever.

### Durability model

| Fact | Stored in |
| --- | --- |
| Solved/accepted | Repo receipt + site evidence |
| In-flight work | Repo lease/event ledger |
| Human visibility | Paperclip issue |
| Agent run | Paperclip run, disposable |
| Checkout | Untrusted cache |

Paperclip API writes use idempotency keys. Every issue mutation includes the part
key, attempt, and fence token. An uncertain write is treated as `BLOCKED`, not success.

### Migration path

1. Add `.aoc/events/` and `.aoc/receipts/` schema; make `.aoc/progress.json` derived.
2. Import existing `progress.json` into initial events; give every accepted part a receipt.
3. Put existing acceptance/site evidence into the repo; anything unverifiable becomes
   `REPAIR_REQUIRED`.
4. Replace `Controller.select()` with `repair + select from reducer`.
5. Disable the old routine trigger; install one canonical routine.
6. Run old and new controllers in shadow mode for a few days; compare decisions.
7. Cut over; leave old scripts as read-only migration tools.

### Tradeoffs

Pros:

- lowest new infrastructure,
- works with the existing Fargate/EFS/standing-key setup,
- Paperclip already has watchdogs, blockers, recovery actions, routines, and attention,
- fast to iterate.

Cons:

- Paperclip is not a transactional durable-execution engine; dual writes still need repair,
- timers, fencing, and loop suppression must be custom,
- recovery is best-effort and polling-based,
- state-machine discipline relies on scripts, not an engine enforcing replay.

**Status:** good bridge, not the final resilience target.

---

## Option 2 — Temporal as the durable coordinator

Use Temporal for coordination and timers; keep the repository as canonical truth.
Temporal history is execution evidence, not domain authority.

### Deployment on ECS Fargate

```text
temporal-frontend
temporal-history
temporal-matching
temporal-worker-service
temporal-ui                 # private
aoc-worker                  # custom Python image
RDS/Aurora PostgreSQL       # Temporal persistence + SQL visibility
Secrets Manager             # DB/API keys
EFS                         # Paperclip workspaces only, not Temporal state
```

Temporal Server consists of four independently scalable services: Frontend,
History, Matching, and Worker Service. History throughput depends on History
Shards, which are effectively fixed at setup. Start with SQL visibility and add
Elasticsearch/OpenSearch only if search needs justify it.

### Custom image policy

- **Custom worker image: yes.** Python workflows, activities, and dependencies live there.
- **Custom Temporal Server image: no by default.** Use pinned official
  `temporalio/server`, `temporalio/ui`, and `temporalio/admin-tools` images.
- Schema setup/migrations run as controlled ECS one-off tasks with matching
  `admin-tools`.
- A custom server image is justified only for Go plugins, patches, or custom
  Server Options.

### Workflow model

- `SeasonWorkflow` — schedule, progress query, global coordination.
- `PartWorkflow` — one durable instance per year/day/part.
- `RepairWorkflow` — explicit `REPAIR_REQUIRED` handling.
- `ProjectionWorkflow` — idempotent Paperclip issue/doc writes.

Workflow IDs:

```text
aoc-2015-day-01-part-1
aoc-2015-day-01-part-1-attempt-3
```

Deterministic activity IDs:

```text
submit:2015-01-1:attempt3
commit-receipt:2015-01-1:attempt3
create-issue:2015-01-1:gather:attempt3
```

Temporal retry identity — workflow run ID plus stable activity ID — provides
natural idempotency keys.

### Activities

All IO lives in activities:

- `scan_repo`
- `verify_candidate`
- `query_site`
- `start_paperclip_run`
- `wait_for_result`
- `validate_result`
- `submit_once`
- `commit_receipt`
- `project_issue`
- `expire_lease`

Activities are at-least-once. Every one must be idempotent. The uncertain AoC POST
becomes its own activity outcome that parks the workflow in `UNCERTAIN` and
schedules a site query. Never retry blind.

### Message passing

| Need | Temporal primitive |
| --- | --- |
| “What state is this part in?” | Query |
| “Paperclip task updated / stop / operator note” | Signal |
| “Approve submission and return status” | Update |

Updates are useful for approval gates because they can read and write workflow
state while the caller waits. Do not assume Temporal Cloud's documented exact
limits apply to self-hosted deployments; verify local config.

### Long-running agents

Avoid one giant “solve puzzle” activity. Preferred model:

1. activity starts Paperclip run and returns `run_id`,
2. workflow waits on a signal or bounded polling timer,
3. activity validates the result document,
4. reducer advances state.

If an activity itself is long, it must heartbeat at meaningful checkpoints, use a
heartbeat timeout shorter than start-to-close, and resume from checkpointed state
on retry. Keep heartbeat details small.

### Determinism rules

Workflow code must not use:

- wall-clock reads except `workflow.now()`,
- direct HTTP, Git, filesystem, or DB calls,
- LLM SDK calls,
- random values except deterministic derivation,
- mutable module-level state.

Use `workflow.sleep()` for timers, signals for inbound events, queries for state,
updates for approvals, and continue-as-new for long histories.

Continue-as-new sharp edges:

- unprocessed signals can be lost,
- child workflows may be affected by parent-close policy,
- external callers caching run IDs break,
- carried state schema must remain compatible.

### Temporal-specific testing

- workflow integration tests with mocked activities,
- time-skipping tests for AoC unlock windows, lease expiry, 429 backoff, rate limits,
- replay CI with exported production/staging histories, including continue-as-new boundaries,
- activity retry/idempotency tests with duplicate completions,
- heartbeat/cancellation tests for long activities,
- ECS chaos POC: kill worker mid-activity, restart Temporal services, break DNS, force DB failover.

### ECS Fargate POC gate

Temporal has official Docker Compose and Kubernetes Helm paths, but no official ECS
Fargate production reference architecture. A community CDK proof of concept exists,
and community reports describe Ringpop / `TEMPORAL_BROADCAST_ADDRESS` bootstrap
problems.

Before committing:

1. deploy official pinned images,
2. verify frontend/history/matching/internal-worker discovery,
3. verify Ringpop membership across Fargate tasks,
4. verify RDS/Aurora persistence,
5. run schema migration via `admin-tools`,
6. kill and restart a worker mid-activity,
7. keep UI private,
8. monitor persistence and workflow metrics.

### Relevant precedent

Temporal Code Exchange has [AgentOfCode](https://temporal.io/code-exchange/agent-of-code.md),
a Python workflow that iteratively solves Advent of Code problems. It uses timeouts,
throttled retries, cached inputs, GitHub progress tracking, and avoids hammering AoC.

Caveat: community-contributed and not reviewed by Temporal. Treat it as precedent,
not an official reference architecture.

### Tradeoffs

Pros:

- mature durable timers, retries, backoff, signals, queries, replay,
- excellent observability via Temporal UI,
- crash recovery is a platform property, not a custom script,
- strongest testing story.

Cons:

- second control plane alongside Paperclip,
- extra services, Postgres, upgrades, monitoring,
- bridge between Temporal and Paperclip must be carefully designed,
- easy to drift into “Temporal history is truth”; policy must prevent that,
- ECS Fargate networking/membership is unverified without a POC.

**Status:** leading target if the ECS Fargate POC passes.

---

## Option 3 — Git-first event-sourced orchestrator

Build a small durable worker whose canonical state is the repository itself.
Temporal-style patterns, but implemented specifically for this domain.

### Architecture

Repo layout as in the shared schema above.

Worker image on ECS Fargate:

- `aoc-orchestrator` — headless, no LLM.
- Postgres for indexes, leases, and outbox:

```text
leases(part_key, fence_token, owner, expires_at)
outbox(command_id, type, payload, attempts, next_attempt_at)
event_cursor(repo_sha, seq)
```

- API bridge to Paperclip for agent dispatch/projection.
- Operator CLI: `aocctl state`, `aocctl repair`, `aocctl replay`, `aocctl lease`.

Use `SELECT ... FOR UPDATE SKIP LOCKED` for outbox workers. Every command carries a
fence token and deterministic command ID. Replaying the repo ledger can rebuild all
derived state. Postgres is an index/cache, not authority.

### Execution loop

1. Poll repository for new events or leases due.
2. Load state by replaying events up to a checkpoint.
3. Call the pure reducer.
4. Insert outbox commands transactionally with cursor update.
5. Execute commands idempotently.
6. Append result events to the repository.
7. Verify commit; advance cursor.

A crash at any point is safe: replay + idempotency + fencing converge.

### Agent integration

Paperclip agents remain executors:

- orchestrator creates/updates Paperclip issues with deterministic `idempotencyKey`,
- agent receives a signed `WorkOrder`,
- agent writes result document,
- worker validates and appends `ResultEvent`,
- reducer decides the next state.

Paperclip issues are always projectable from the ledger.

### Tradeoffs

Pros:

- best alignment with “source of truth remains source-code,”
- full control over invariants and state semantics,
- pure reducer is highly testable; property/model tests are straightforward,
- no dependency on workflow-engine determinism,
- replay from Git works after Paperclip reimport or total orchestrator loss.

Cons:

- you are building a small workflow engine,
- timers, retries, monitoring, and backpressure must be implemented,
- operational visibility must be built,
- highest initial engineering effort.

**Status:** best fallback if Temporal ECS ops are unacceptable; strongest source-code purity.

---

## Engine comparison

| Engine | Durable model | Fit |
| --- | --- | --- |
| Temporal | Code workflows replayed from immutable Event History; activities, signals, queries, updates, schedules | Best overall if replayable durable state and agent loops are core. Main risk: ECS Fargate ops/network POC. |
| Restate | Journaled durable handlers, services, timers, persistent log | Strong alternative with Python SDK, but docs say ECS is unsuitable for Restate clusters due lack of persistent volume attachments; AWS guidance recommends EKS Fargate + EBS + S3. |
| AWS Step Functions Standard | Managed ASL state machine, durable up to 1 year, audit history | Good managed option. Limits: 25,000 history events, 256 KiB payloads, 1 MB definition, 90-day history retention, immutable workflow type. Weaker local replay and rich long-lived entity semantics. |
| AWS Step Functions Express | Short managed workflows | 5-minute execution limit; poor fit for long AoC solve sessions. |
| Dapr Workflow | Durable sidecar engine with activities, child workflows, timers | Good if Paperclip already adopts Dapr; otherwise another platform abstraction. Python supported. |
| Durable Functions | Azure orchestrator/activity/entity functions | Reject for AWS ECS self-hosted requirement. Storage providers are Azure-centric; migration unsupported. |
| Prefect | Python flows/tasks with server state, caching, retries, HITL | Good for Python data pipelines; not event-sourced replay for entity state. |
| Airflow 3.4 | DAG scheduling, resumable tasks since 3.3 | Appropriate for scheduled batch jobs, not primary interactive durable engine. |
| LangGraph | Thread-scoped graph checkpoints | Useful agent framework under Temporal; checkpointers alone are not full durable execution. |
| XState v6 durable | Explicit FSM actor model; `createDurable(...)` experimental | Interesting for modeling, too experimental as primary engine. |
| Conductor OSS | Server-side workflow definitions, decider, sweeper, workers, lock | Viable but heavy: API server, decider, sweeper, system workers, DB, queue, index, distributed lock. |

---

## Testing strategy

The reducer is the test target. Engines are adapters.

### 1. Pure transition tests

For every state × event × guard combination:

- expected next state,
- expected commands,
- no-op for duplicate event,
- rejection for stale fence token,
- timeout behavior.

Use Hypothesis property-based tests for invariants:

- at most one active lease per part,
- no `ACCEPTED` without receipt and site evidence,
- no double submission,
- no transition from `UNCERTAIN` without site query,
- every nonterminal state has deadline or owner,
- repeated events are idempotent.

Optionally specify the machine in TLA+/PlusCal or XState and compare generated traces.

### 2. Scenario fixtures

Must include:

- empty repo, new company,
- populated repo with no Paperclip evidence,
- same company resuming after pause,
- wrong candidate solution,
- site accepted with matching repo code,
- site accepted with no repo code → `NEEDS_OPERATOR`,
- stale checkout,
- empty checkout,
- genuinely diverged checkout,
- duplicate/out-of-order events,
- crash after every effect,
- uncertain AoC POST,
- rate limit,
- lease expiry mid-run,
- two company instances racing,
- finale parts,
- year/day rollover,
- corrupted/missing cursor.

The existing `tests/test_workflow.py` fakes are a good base but currently test
controller logic rather than fault injection.

### 3. Adapter contract tests

- real Paperclip staging company for issue/doc/status semantics,
- real Git fixture repos for clone/sync/receipt verification,
- recorded AoC HTTP fixtures; no live submission in normal CI,
- verify idempotency keys with intentionally duplicate API responses.

### 4. Chaos/fault injection

In staging:

- kill worker after each command,
- duplicate signals,
- delay site responses beyond timeout,
- force lease expiry,
- corrupt one event,
- reimport company mid-flight,
- replay ledger into an empty orchestrator,
- assert convergence to the same canonical state.

### 5. Temporal-specific tests

- time-skipping tests for lease/rate-limit timers,
- activity mock tests for all external effects,
- replay every captured production history in CI,
- determinism lint: workflow code may not import HTTP/Git/clock/random modules,
- heartbeat and cancellation tests,
- ECS service-discovery and DB-failover POC tests.

---

## Final recommendation

Build the shared pure state machine and its test suite first, regardless of engine.
That is the durable asset.

Then:

1. Use Option 1 as a bridge to introduce receipts, reducer, and repair.
2. Build Temporal workflows in shadow mode with fake activities.
3. Run the ECS Fargate POC.
4. If the POC passes, move `REPAIR_REQUIRED`, `SUBMITTING`, and `UNCERTAIN` into
   Temporal first — the riskiest states — then all part orchestration.
5. If the POC fails or ops burden is unacceptable, fall back to Option 3: Git-first
   custom worker using the same reducer and tests.

Non-negotiables:

- repo remains source of truth,
- state repair is a first-class workflow,
- all external effects are idempotent activities,
- no blind resubmission after uncertain AoC POST,
- replay CI fails on nondeterminism,
- Paperclip issues are projections only,
- ECS Fargate Temporal POC must pass before full commitment.

---

## Key source URLs

### Temporal

- https://docs.temporal.io/temporal-service/temporal-server.md
- https://docs.temporal.io/temporal-service/persistence.md
- https://docs.temporal.io/self-hosted-guide/deployment.md
- https://docs.temporal.io/self-hosted-guide/production-checklist.md
- https://docs.temporal.io/develop/python/workflows/basics.md
- https://docs.temporal.io/evaluate/features/workflow-message-passing.md
- https://docs.temporal.io/schedule
- https://docs.temporal.io/design-patterns/long-running-activity.md
- https://docs.temporal.io/design-patterns/continue-as-new.md
- https://docs.temporal.io/design-patterns/saga-pattern.md
- https://docs.temporal.io/develop/python/best-practices/error-handling.md
- https://docs.temporal.io/develop/python/best-practices/testing-suite.md
- https://docs.temporal.io/develop/python/integrations/langgraph.md
- https://github.com/temporalio/platform-hub/blob/main/docs/ai-engineering/reference-architecture.md
- https://github.com/temporalio/platform-hub/blob/main/docs/ai-engineering/patterns.md
- https://temporal.io/code-exchange/agent-of-code.md
- https://github.com/JasonSteving99/agent-of-code
- https://github.com/Progymedia/temporalio-cluster-cdk
- https://community.temporal.io/t/deploying-temporal-io-on-ecs-fargate/18606

### Alternatives

- https://docs.restate.dev/server/overview.md
- https://docs.restate.dev/server/deploy/aws.md
- https://docs.aws.amazon.com/step-functions/latest/dg/choosing-workflow-type.html
- https://docs.aws.amazon.com/step-functions/latest/dg/limits-overview.html
- https://docs.dapr.io/developing-applications/building-blocks/workflow/workflow-overview/
- https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-overview
- https://docs.prefect.io/v3/concepts/tasks.md
- https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/resumable-tasks.html
- https://docs.langchain.com/oss/python/langgraph/durable-execution.md
- https://stately.ai/docs/xstate/v6/durable-execution
- https://docs.conductor-oss.org/devguide/running/deploy.html

### Paperclip platform context

- Paperclip durable continuation scheduler:
  `/home/yoda/Development/Home/paperclip/doc/architecture/durable-continuation-scheduler.md`
- Paperclip heartbeat protocol:
  https://raw.githubusercontent.com/paperclipai/paperclip/master/docs/guides/agent-developer/heartbeat-protocol.md
- Paperclip task watchdogs:
  https://raw.githubusercontent.com/paperclipai/paperclip-docs/main/docs/guides/projects-workflow/task-watchdogs.md
- Paperclip routines:
  https://raw.githubusercontent.com/paperclipai/paperclip-docs/main/docs/guides/projects-workflow/routines.md
- Paperclip AWS ECS deployment:
  https://raw.githubusercontent.com/paperclipai/paperclip/master/docs/deploy/aws-ecs.md
