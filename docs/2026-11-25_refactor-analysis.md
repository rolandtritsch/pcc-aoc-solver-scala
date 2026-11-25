# AoC company refactor analysis — 2026-11-25

## Objective

Analyze `pcc-aoc-solver-scala` and propose a ground-up refactor centered on an
explicit, testable, robust state machine. Compare a Paperclip-native design, an
external durable workflow engine (Temporal), and a git-first custom alternative.

The user's governing constraint:

> The source of truth remains to be the source-code. When there is not
> evidence/task available in the company that a given problem has already been
> solved the company should go through a state-repair phase and check what is
> already solved. If a solution exists and if the result can be successfully
> submitted then the day/problem is considered to be solved.

Absence of a Paperclip task is **not** evidence that a part is unsolved — it
triggers state repair from the repository and the AoC site, not a stuck state.

---

## Authority model

| Concern | Authority |
| --- | --- |
| Canonical fact store | Source repository: committed code plus append-only acceptance receipts/events |
| External acceptance oracle | Authenticated adventofcode.com page |
| Execution coordinator | Paperclip-native, Temporal, or custom worker depending on option |
| Ephemeral projection | Paperclip issues, tasks, documents, comments |
| Untrusted cache | EFS-staged checkout used by an individual agent run |

The LLM/agent never decides the next state. It receives an immutable
`WorkOrder` and emits a signed `ResultEvent`. A deterministic reducer advances
state.

---

## Why the current design is fragile

Today's workflow is a distributed state machine spread across Paperclip
issues/tasks/documents, `.aoc/progress.json`, the authenticated AoC site,
disposable EFS checkouts, local `flock`, and agent heartbeats/routines — no
single transaction spans those stores. Known failure modes: disabled
heartbeats plus a paused `daily-selection` routine with `coalesce_if_active`;
strict title/description parsing; a full 2015+ rewalk in `Controller.select()`;
non-atomic result/disposition/progress/Git writes; a `Blocked` handler that
doesn't finish a routine occurrence; `flock` budgets shorter than 30-minute
solver runs; stale/empty/diverged EFS workspaces; operator-only recovery and
narrow observability; Paperclip's ~30s stranded-issue reconciliation looping
`issue_continuation_needed` when no converged disposition is written.

`DESIGN.md` already flagged the unresolved source-of-truth question. The new
constraint resolves it: repo is canonical, site is the oracle, Paperclip is a
projection, the checkout is a cache.

---

## Shared state machine

Common to all three options below; the engine only coordinates it.

```text
PartKey  = year/day/part
Lease    = { lease_id, fence_token, owner, expires_at }
Receipt  = { part_key, commit_sha, answer, site_account,
             observed_at, page_evidence, submission_id? }
Event    = { event_id, part_key, type, payload, occurred_at,
             actor, lease_token, idempotency_key }
Command  = { command_id, type, target, payload, fence_token, idempotency_key }

reduce(state, event) -> (new_state, [commands])
```

The reducer is pure. Adapters execute commands idempotently (Git, AoC site,
Paperclip API, agent dispatch); commands carry fence tokens so stale owners
can't advance state.

**States:** `DISCOVERED`, `REPAIR_REQUIRED`, `REPAIRING`, `UNSOLVED`,
`CANDIDATE_PRESENT`, `LOCAL_VERIFIED`, `LEASED`, `GATHERING`/`SOLVING`/
`PUBLISHING`, `SUBMITTING`, `UNCERTAIN`, `ACCEPTED` (terminal), `REJECTED`,
`RATE_LIMITED`, `BLOCKED`, `NEEDS_OPERATOR`, `SUPERSEDED`. Finale parts skip
solve/submit transitions.

**Riskiest transitions** (the rest follow the obvious pattern):

| From | Event / guard | To | Effect |
| --- | --- | --- | --- |
| `LOCAL_VERIFIED` | `SubmitAttempted` | `SUBMITTING` | One POST, idempotency key |
| `SUBMITTING` | `UncertainResponse` | `UNCERTAIN` | Park; schedule site query; **never** blind-retry |
| `UNCERTAIN` | site still unsolved | `NEEDS_OPERATOR` | Forbid repeat POST |
| any active | lease expired | `REPAIR_REQUIRED` | Revoke fence token |
| `REPAIRING` | site accepted, no/mismatched candidate | `NEEDS_OPERATOR` | No fabrication |

**State-repair procedure** (first-class state, not an operator script):
acquire a fenced lease → clone fresh (never trust staged EFS) → enumerate
parts, read receipts/events, ignore Paperclip absence → per part, reconcile
candidate code + site truth → project results into Paperclip idempotently as
*already-terminal* issues (no accidental agent wake) → release lease only
after receipt + projection commits are verified.

**Repo schema:**

```text
.aoc/
  events/YYYY/D##/part#.jsonl     # append-only, canonical
  receipts/YYYY/D##/part#.json    # acceptance receipts, canonical
  state/YYYY/D##/part#.json       # derived snapshot, checksummed
  progress.json                   # derived convenience projection only
```

`.aoc/events/` and `.aoc/receipts/` are canonical; `progress.json` and
Paperclip issues are derived projections — **nothing else may write
`progress.json` directly**; enforce with a generated-file lint/test, since the
original design drifted exactly this way once before.

---

## Option A — Paperclip-native reconciling controller

No new workflow engine. Paperclip remains the coordinator; issues become
projections/leases, not authority. Every controller tick **recomputes** state
from repo + site rather than trusting stored history — state repair isn't a
special mode bolted onto an event log, it *is* the only mode (the
Kubernetes-controller "observe, diff, act, repeat" pattern), generalizing the
existing `next_part()` pattern in `aoc_cycle_gate.py` that the original
analysis already called "a good pattern to generalize."

**Architecture:** keep the four capabilities (CTO/controller, Gatherer,
Solver, Submitter); only the controller owns transitions; specialists are
stateless (`WorkOrder` in, signed `ResultEvent` out); add `aoc_state.py` (pure
reducer + repo ledger/receipts) and `aoc_repair.py`; use Paperclip natives
(blockers, watchdogs, routines, recovery actions) for attention only; gate
agent wake until repo/site state is reconciled; bound continuations to one
per part per lease window with an explicit converged disposition.

**Durability/migration:** solved/accepted facts live in the repo receipt +
site evidence; in-flight work lives in the repo lease/event ledger; Paperclip
issues are disposable. Migration: add the `.aoc/` schema, import existing
`progress.json` into initial events (treat anything unverifiable as
`REPAIR_REQUIRED` rather than trusting it), replace `Controller.select()` with
repair+reducer, run old/new controllers in shadow mode before cutover.

**Good**
- Lowest new infrastructure; works with the existing Fargate/EFS setup and
  Paperclip's existing watchdogs/blockers/recovery actions.
- Reconciliation-first design directly answers `AGENTS.md`'s own lesson
  ("self-healing beats bespoke recovery scripts") instead of adding a second
  recovery path alongside an event log.
- Fast to iterate; smallest blast radius of the three options.
- Trivially satisfies "no fabrication without evidence" — every tick
  re-derives conclusions from live sources, never from a possibly-stale log.

**Bad**
- Weaker audit trail: no append-only record of *why* a decision was made at a
  point in time unless you deliberately log each reconcile pass as an
  advisory (non-authoritative) event stream.
- Timers, fencing, and loop suppression are all custom, hand-maintained code,
  not a platform guarantee.
- Doesn't map cleanly onto a 30-minute in-flight solver run — still needs a
  lease/claim mechanism bolted on, so "just recompute from scratch" isn't
  free for long-running work.

**Ugly**
- Recovery stays best-effort and polling-based; nothing stops a future script
  from writing `progress.json` directly again unless enforcement (lint/CI
  check) ships in the same change, not as a follow-up.

**Status:** best default for the simplest v1 that still satisfies the
governing constraint — worth proving out before investing in either option
below.

**Spike result (2026-11-25):** a throwaway, read-only, no-network prototype
of `reconcile()` was run against real data in the `scala3-aoc` solutions
repo (17 committed parts, 2015 days 1–9) plus two scripted synthetic cases.
Findings:
- Confirmed a real, pre-existing drift: `LAST.md` claims `2015/04/2` while
  `.aoc/progress.json`'s receipt ledger shows `2015/09/1` accepted. The loop
  reproduced the correct frontier with **no explicit repair step**, because
  it never reads `LAST.md` as authority — direct evidence for the
  self-healing claim above, against a real, not synthetic, discrepancy.
- Two ticks over all 17 real parts produced byte-identical output
  (idempotent/convergent).
- Two scripted synthetic cases confirmed the hardest invariants hold without
  any live network access: site-accepted-but-no-repo-code → `NEEDS_OPERATOR`
  (never fabricates); uncertain-submission → `UNCERTAIN` → re-query →
  `ACCEPTED` (never blind-retries).

No red or yellow flags surfaced that would block choosing Option A. The
spike was narrow by design — only already-solved historical days, no live
site traffic, no in-flight solver run, no concurrent instances — so it
cannot speak to the two risks already named above (lease/claim handling for
a real 30-minute solve, and racing company instances). Those are the right
next spikes before full commitment, not new risks this one surfaced.

**Lease/claim spike result (2026-11-25):** ran the `Lease{lease_id,
fence_token, owner, expires_at}` primitive against two **real** `sbt
--server --batch 'clean; compile; testOnly aoc2015.day01.Day01Test; run'`
invocations — the exact command shape the Solver stage actually uses
(`publication.py`/`common.py`), not a simulated sleep. Read-only: no git
writes, no AoC site, no Paperclip.
- **Happy path:** real build took 28s; one heartbeat renewal mid-build kept
  the lease alive; the build produced the real answer (`Day01 - part1:
  138`, matching the known `progress.json` receipt); the resulting effect
  was accepted under the still-valid fence token.
- **Stale/crashed worker:** a lease was deliberately starved of heartbeats
  (TTL=8s) while a second real build ran in the background. The reconciler
  independently observed expiry and bumped the fence token (repair, no
  coordination with the original worker). When the original subprocess
  finished 8s later with a *correct* answer, its submission was **rejected**
  for carrying a stale fence token — only the repaired owner's effect was
  accepted.

This closes the lease/claim risk named above against real, not simulated,
long-running work. The only remaining unexercised risk from the original
list is racing/concurrent company instances.

**Racing-instances spike result (2026-11-25):** real OS-level process
contention, not simulated/in-memory locking, for the same lease on one
part_key — every racer is a separate process using `fcntl.flock(LOCK_EX |
LOCK_NB)` on a shared lock file as the exclusivity primitive (the same
non-blocking "try, don't wait" shape as a `SELECT ... FOR UPDATE SKIP
LOCKED` acquire).
- **Stress test:** 10 real concurrent processes raced for one lease, 5
  trials (50 total race attempts) — exactly one winner every trial, zero
  double-acquires.
- **Realistic scenario:** exactly 2 real instances raced for `2015/01/1`
  (modeling two company instances both believing they own a part, e.g.
  after a reimport). The losing instance was denied **before attempting any
  work at all** — it never ran sbt, never risked a duplicate submission. The
  winner ran a real (non-`clean`) `sbt testOnly ...; run` and reproduced the
  correct, known answer (`138`).

This closes the last unexercised risk from the original Option A caveats.
Combined with the two prior spikes, Option A has now been checked against
real historical drift, a real long-running solve under lease, and real
concurrent instances, with no red or yellow flags in any of the three.

---

## Option B — Temporal as durable coordinator (ECS Fargate)

Temporal provides coordination and timers; the repository stays canonical.
Temporal history is execution evidence, not domain authority.

**Architecture:** `temporal-frontend`/`history`/`matching`/`worker-service`/
`ui` (private) + a custom `aoc-worker` Python image + RDS/Aurora Postgres +
Secrets Manager; EFS stays scoped to Paperclip workspaces only. Workflows:
`SeasonWorkflow`, `PartWorkflow` (one durable instance per part), `
RepairWorkflow`, `ProjectionWorkflow`; deterministic workflow/activity IDs
double as idempotency keys. All IO lives in activities (`scan_repo`,
`query_site`, `submit_once`, `commit_receipt`, …), all at-least-once and must
be idempotent; an uncertain AoC POST parks the workflow in `UNCERTAIN` and
schedules a site query rather than retrying blind. Use the official pinned
`temporalio/server`/`ui`/`admin-tools` images; a custom server image is only
justified for Go plugins/patches.

**Durability/migration:** crash recovery and replay are platform properties.
Build workflows in shadow mode with fake activities first; cut real traffic
over state-by-state, riskiest first (`REPAIR_REQUIRED`, `SUBMITTING`,
`UNCERTAIN`).

**Good**
- Mature durable timers, retries, backoff, signals/queries/updates, replay —
  the strongest testing and observability story of the three.
- Crash recovery is a platform property, not custom script logic.
- A real precedent exists: Temporal's own Code Exchange hosts
  [AgentOfCode][agent-of-code], a community Python workflow solving AoC with
  timeouts, throttled retries, and GitHub progress tracking — useful shape
  reference, though community-contributed and not Temporal-reviewed.

**Bad**
- A second control plane next to Paperclip: five more services, Postgres,
  upgrades, monitoring — a real ongoing operational tax for a single
  operator, never priced against that cost in the original plan.
- Easy to drift into "Temporal history is truth"; policy must actively
  prevent that from happening in practice, not just on paper.
- The 5-layer Temporal-specific test list (replay CI, determinism lint,
  time-skipping, heartbeat/cancellation, ECS chaos) is a multi-week project
  on its own for a system solving a few hundred AoC parts a year.

**Ugly**
- The ECS Fargate networking/membership risk is not a historical footnote:
  a live Oct 28, 2025 community thread shows the exact same Ringpop /
  `TEMPORAL_BROADCAST_ADDRESS` bootstrap failure the original plan cited,
  with the same root cause traceable back to at least 2020–2022 ([GitHub
  #2630][temporal-2630], [community thread 2025][temporal-2025],
  [community thread 2020][temporal-2020]). This is a long-standing,
  unresolved class of bug, not something recent releases fixed. Temporal has
  no official ECS Fargate reference architecture — only community
  Terraform/CDK starters. **Run this POC first and cheap, before building
  Option A out, not after** — the realistic prior is "likely to need
  nontrivial networking workarounds or fail outright," which should drive
  sequencing, not just risk disclosure.

**Status:** leading target *only if* an early, isolated ECS Fargate POC
passes; otherwise fall back to Option C.

---

## Option C — Git-first durable worker on a Postgres durable-execution library

Canonical state is the repository itself; a small worker coordinates it. Where
the original plan proposed hand-rolling leases/outbox/retry tables from
scratch, use a maintained Postgres-native durable-execution library (e.g.
[DBOS][dbos]) for that machinery instead of writing it bespoke — this keeps
"build your own" honest about how much is genuinely custom (the reducer, the
git ledger, the Paperclip bridge) versus reusable (durable retries,
checkpointing, step history), all on infrastructure already planned (Postgres
as index).

**Architecture:** `aoc-orchestrator` worker (headless, no LLM) on ECS Fargate;
durable steps/checkpoints live as Postgres rows via the library — no separate
control-plane server, no gossip/cluster layer to bootstrap (unlike Option B's
Ringpop risk); an API bridge to Paperclip for dispatch/projection; an operator
CLI (`aocctl state|repair|replay|lease`). Replaying the repo ledger can always
rebuild derived state; Postgres is an index/cache, never authority.

**Durability/migration:** a crash at any point is safe — replay, idempotency,
and fencing converge. Paperclip agents remain pure executors: orchestrator
creates issues with deterministic idempotency keys, agent returns a result
document, worker validates and appends a `ResultEvent`, reducer decides next
state.

**Good**
- Best alignment with "source of truth remains source-code"; full control
  over invariants; the pure reducer is highly testable (property/model tests
  are straightforward).
- No gossip-network/service-discovery risk class at all — the dominant cause
  of Option B's Ugly finding structurally doesn't exist here.
- Using a maintained library for the hard, boring part (durable
  retries/checkpointing) is materially less engineering than the original
  plan's fully hand-rolled outbox/lease schema, while keeping the same
  operational footprint (just Postgres).

**Bad**
- The library itself is young (2024–2026 adoption), with thin multi-year
  production evidence — a real caveat, though no worse than the durability
  ceiling a hand-rolled outbox would already have (bounded by this Postgres
  instance's own backup/HA story either way).
- Still requires building operational visibility (dashboards, alerting) from
  scratch — Paperclip and Temporal both give you more of this for free.
- Timers, retries, and backpressure discipline still need to be designed
  deliberately even with the library doing checkpointing.

**Ugly**
- Git-as-canonical-oracle for *workflow orchestration* (not just issue
  tracking) has essentially no direct precedent to lean on. The closest prior
  art, [git-bug][git-bug], is explicitly **not recommended by its own
  maintainers** for multi-committer projects because concurrent writers
  diverge before merge — this project's single-writer nature sidesteps that
  specific failure mode, but the original plan asserts the git-ledger design
  as settled across all three options without flagging that it's genuinely
  novel ground, not a proven pattern being reused.

**Status:** strongest fallback and best source-code-purity fit if Option B's
POC fails or its ops burden is unacceptable — and, given the library
substitution above, cheaper to reach than the original plan's fully
hand-rolled version.

---

## Engine landscape (why nothing else made the cut)

Already considered and set aside with specific reasons: **Restate** (AWS
guidance itself says ECS lacks the persistent-volume story Restate clusters
need); **Step Functions Express** (5-minute execution cap, wrong for 30-minute
solves) and **Standard** (workable but weaker replay/entity semantics than
Temporal, with real history/payload limits); **Durable Functions** (Azure-only
storage providers, rejected for an AWS-only shop); **Dapr Workflow** (fine if
Paperclip adopted Dapr already — it hasn't); **Prefect**/**Airflow** (built for
scheduled data pipelines, not entity-level durable state); **LangGraph**
(checkpointers alone aren't full durable execution); **XState v6 durable**
(too experimental to depend on); **Conductor OSS** (viable but a heavier
server+decider+sweeper+queue+index footprint than this volume justifies);
**Hatchet** (same shape problem — a real multi-component control plane sized
for far higher throughput than "hundreds of transactions a year");
**Inngest self-hosted** (most of its value is the managed hosting; self-hosted
ops cost approaches Temporal's without Temporal's maturity, plus DSL
lock-in); **Resonate/Durable Promises** (elegant spec, too little production
evidence yet); **Windmill** (wrong abstraction level — an internal-tooling
platform, and its own maintainers steer users away from Fargate); **Cadence**
(not dead, but strictly Temporal's older, less-invested-in sibling — no
reason to prefer it over Option B).

---

## Testing strategy (by priority, not by engine)

**Now (must-have, any option):** pure reducer transition tests for every
state × event × guard (expected next state/commands, no-op on duplicate
event, rejection on stale fence token); Hypothesis property tests for the
core invariants (at most one active lease per part; no `ACCEPTED` without
receipt + site evidence; no double submission; no transition from `UNCERTAIN`
without a site query; every nonterminal state has a deadline/owner); the
~15 scenario fixtures already enumerated (empty repo, resume-after-pause,
wrong candidate, site-accepted-no-code, diverged checkout, duplicate/
out-of-order events, racing instances, finale parts, year rollover,
corrupted cursor, etc.) — `tests/test_workflow.py`'s existing fakes are a
good base but currently test controller logic, not fault injection; extend
them for that.

**Before production cutover:** adapter contract tests (real Paperclip
staging, real Git fixtures, recorded AoC HTTP fixtures, no live submission in
CI); chaos/fault injection in staging (kill worker after every command,
duplicate signals, corrupt an event, reimport mid-flight, assert convergence
to the same canonical state).

**Only if Option B is chosen:** replay CI against exported production
histories, a determinism lint banning HTTP/Git/clock/random imports from
workflow code, heartbeat/cancellation tests, and an ECS service-discovery/DB-
failover POC test. TLA+/PlusCal cross-checking is optional and should wait
for evidence of recurring state bugs, not be built speculatively up front.

---

## Final recommendation

Build the shared pure reducer and its must-have tests first, regardless of
which option wins — that's the durable, portable asset across all three.

**Update, 2026-11-25:** Option A's reconciliation loop has been spiked three
times with no red/yellow flags in any of them — against real historical
repo data, against the lease/claim mechanism under two real `sbt` solver
builds, and against real OS-level racing/concurrent company instances (see
Option A's Spike results above). All three caveats originally raised
against Option A are now closed with evidence from real builds and real
process contention, not simulation. Option A is the recommended direction.
Keep Option B's ECS Fargate POC on the backlog as a cheap, isolated,
low-priority check only if implementation surfaces a concrete need for
Temporal's durability/observability guarantees; Option C (DBOS) remains the
documented fallback if Option A hits a blocker during real implementation
that these spikes didn't surface.

**Non-negotiables:** repo remains source of truth; state repair is a
first-class behavior, not an operator script; all external effects are
idempotent; no blind resubmission after an uncertain AoC POST; Paperclip
issues are projections only, never authority; if Option B is chosen, replay
CI must fail on nondeterminism and the ECS Fargate POC must pass before full
commitment.

---

## Implementation status — 2026-11-25

Option A is implemented and live. `aoc_state.py`/`aoc_repair.py` exist as
real, tested modules; `Controller.select()` calls `next_unsolved()` for
every reconciliation decision (not a parallel/unused abstraction); a fresh
company is deployed with its `daily-selection` routine renamed/retimed to
an hourly reconcile tick (`0 * * * * UTC`, still paused pending explicit
enablement). 104 tests pass, `compileall` clean.

Closed against the non-negotiables above:
- State repair is first-class: every `select()` call re-derives truth from
  repo + site, self-healing drift (a real `LAST.md`/`progress.json`
  discrepancy in `scala3-aoc` was used as a live fixture) with no special
  repair step.
- No blind resubmission: an existing candidate is verified and submitted
  directly when found, skipping `gather`/`solve`; a rejection is tracked by
  the pre-existing generic rejection path, proven by test.
- Nothing writes `.aoc/progress.json` outside the sanctioned projector —
  enforced by a structural test, not just convention.
- Lease/fencing and racing-instances risks closed against real `sbt`
  builds and real OS-process contention (50/50 trials), not simulation.

Deliberately descoped, with reasoning recorded rather than silently
dropped:
- The `.aoc/events/`/`.aoc/receipts/`/`.aoc/state/` schema in the shared
  design above was written for the event-sourced options (B/C). Option A's
  entire value proposition is *not* needing an event log; `progress.json`
  with inline receipts already is its canonical store. Building the
  separate schema would be unused ceremony for the option actually chosen.
- Adapter-contract/chaos tests are done at local scope only (real git
  fixture repos, canned site responses) — a real staging Paperclip company
  and live AoC traffic were deliberately deferred rather than stood up
  speculatively; add them if the local-scope tests stop being sufficient.
- `aoc_repair.repair()` (the lease-fenced full-calendar rescan, for running
  reconciliation outside of Paperclip entirely) and `operators/aoc.py`'s
  `reconcile` CLI action (a Paperclip-task-dispatched, read-only
  `select(authorize=False)` check) were both removed 2026-11-25 — neither
  had a real caller or test coverage, and every real tick (routine or
  manual authorization) already self-heals via `next_unsolved()` as a side
  effect. `operators/OPERATIONS.md` updated to match: there is no longer a
  separate dry-run reconcile step — reconciliation only happens as part of
  a real, authorized CTO tick.

---

## Key sources

- [Temporal self-hosted deployment guide][temporal-deploy]
- [Temporal production checklist][temporal-checklist]
- [Temporal AgentOfCode precedent][agent-of-code]
- [Temporal community: ECS Fargate Ringpop bootstrap failure, Oct 2025][temporal-2025]
- [Temporal GitHub issue #2630: Ringpop bootstrap, 2020][temporal-2630]
- [Temporal community: Ringpop bootstrap, 2020][temporal-2020]
- [Restate AWS deployment guidance][restate-aws]
- [AWS Step Functions limits][sfn-limits]
- [DBOS durable execution][dbos]
- [git-bug: git-as-database precedent and its own caveats][git-bug]
- [Postgres outbox + `SKIP LOCKED` pattern][pg-outbox]
- Paperclip platform context: durable-continuation scheduler, heartbeat
  protocol, task watchdogs, routines, and AWS ECS deploy guide — see
  `/home/yoda/Development/Home/paperclip/doc/architecture/` and
  `paperclipai/paperclip-docs` guides.

[agent-of-code]: https://temporal.io/code-exchange/agent-of-code.md
[temporal-deploy]: https://docs.temporal.io/self-hosted-guide/deployment.md
[temporal-checklist]: https://docs.temporal.io/self-hosted-guide/production-checklist.md
[temporal-2025]: https://community.temporal.io/t/deploying-temporal-io-on-ecs-fargate/18606
[temporal-2630]: https://github.com/temporalio/temporal/issues/2630
[temporal-2020]: https://community.temporal.io/t/unable-to-bootstrap-ringpop/1597
[restate-aws]: https://docs.restate.dev/server/deploy/aws.md
[sfn-limits]: https://docs.aws.amazon.com/step-functions/latest/dg/limits-overview.html
[dbos]: https://github.com/dbos-inc/dbos-transact-py
[git-bug]: https://github.com/git-bug/git-bug
[pg-outbox]: https://dev.to/poojang/you-probably-dont-need-kafka-a-durable-outbox-and-job-queue-in-plain-postgres-4791
