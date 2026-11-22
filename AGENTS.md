# Lessons learned

This file is institutional memory for whoever (human or Claude) next works on
this package, especially a major refactor. It is not user-facing documentation
(see [README.md][readme] for that) and not runtime agent instructions (see
`agents/*/AGENTS.md` for that — those get synced into the live company).
This file records what broke, why, what fixed it, and what to avoid repeating,
distilled from the recovery/redesign work in November 2026.

Treat anything below tagged **(unresolved)** as still-open; do not assume it
was fixed just because a workaround is described.

This includes material harvested from the immediately preceding session in
this same project (the one that migrated agents to the dedicated Fargate
runtime and removed the WatchDog/ModelTester agents, commits `f1a903e` and
`a445951`), not just the session that did the `daily-selection` latency fix.

## The central open design question: where is the source of truth?

Every major bug this session hit — the slow reconciliation path, the
reimport amnesia that motivated `LAST.md`, the staged-workspace divergence
that was never fully resolved — traces back to the same unresolved question:
**when the system needs to know "what's done and what's next," which store
actually gets to answer, and why?** There are (at least) four candidates in
play right now, and this package currently gives an *implicit*, inconsistent
answer depending on which script you're reading. A refactor should make this
answer **explicit and composed on purpose**, not rediscover it piecemeal the
way this session did.

**The four candidate stores, and what each one actually knows:**

1. **The GitHub repo (`scala3-aoc`).** Tells you whether code that *looks*
   solved exists and is committed. Durable, versioned, survives a company
   being archived/deleted/reimported. Does **not** tell you whether that
   code was ever actually accepted anywhere, whether something is
   currently in flight for that day, or whether a prior attempt was
   rejected and is waiting on repair. A commit existing is evidence, not
   proof.
2. **The AoC website.** The only thing that can answer "is this *actually*
   accepted," independent of all our own infrastructure — genuinely
   authoritative for that one question. Does **not** tell you whether our
   current code reproduces that answer, why something failed, or what's in
   progress. Rate-limited and session-dependent, so it's correct as an
   arbiter, too slow/fragile to be the primary driver of every decision.
3. **Paperclip's own issues/tasks for the company.** The only store that
   knows about *live workflow state* — a run currently in progress, a
   rejected attempt waiting for repair, a blocked handoff — which neither
   the repo nor the site can express at all. But it is scoped to a single
   company's lifetime: archiving or reimporting the company (something this
   package explicitly needs to support) throws all of it away. That's the
   amnesia problem `LAST.md` was built to route around, and it's also why
   the original gate design (replaying issue history to compute progress)
   silently assumed "this company has been running continuously since the
   beginning of the season," which was never actually true.
4. **Whatever git state happens to be checked out in a run's EFS-staged
   workspace.** This is **not a source of truth and must never be treated
   as one** — it is a cache, and this session proved the cache is
   unreliable: staged copies have been found empty, stale by many commits,
   and diverged with locally-committed-but-unpushed work. The `LAST.md`
   redesign's worst bug was implicitly trusting this cache (reading
   `LAST.md` straight out of whatever happened to be checked out) instead
   of treating every read of it as "unverified until synced."

**The actual insight**: no single store is sufficient, because each one
answers a *different* question, and the four questions are all genuinely
needed:
   - "Does plausible code exist?" → repo.
   - "Was it actually accepted?" → site.
   - "Is something in flight or rejected right now, in *this* company's
     current lifetime?" → Paperclip issues.
   - "What does a given run actually see?" → the staged workspace, and
     only after it's been explicitly verified/synced against the repo —
     never trusted on its own.

Any robust design has to compose these on purpose, not default to whichever
one happened to be convenient to read from a given script. And it has to
work for every one of these starting conditions, which a refactor should
treat as explicit test cases, not afterthoughts:

   - A brand-new company with a brand-new, empty repo (day 0 of a season).
   - A brand-new company pointed at a repo that **already has solutions in
     it** (this session's actual situation after every archive+reimport —
     and the scenario that most exposed the amnesia problem).
   - The *same* company resuming after a pause/outage, where Paperclip issue
     history is still valid and shouldn't need to be rebuilt from scratch.
   - A day where the repo has a *failing or wrong* solution — "a file
     exists for this day" is not the same as "this day is done," and the
     design must not conflate the two.
   - The site says a part is accepted but the repo has no commit that
     explains it (manual intervention, a reverted commit, a different
     company's work) — there's no way to fabricate a provenance-bearing
     commit for this; it has to be a recognized, explicit "can't
     reconcile automatically" state, not a silent guess either way.
   - Two company instances somehow both pointed at the same solution repo
     (shouldn't happen, but a cursor-advancing design like `LAST.md` has no
     protection against a race if it did).
   - A staged workspace whose local git state has silently drifted from
     origin (confirmed to happen in practice this session) — any design
     that reads repo state inside a run must treat that read as unverified
     until it has itself confirmed the sync, every time, not just on first
     use.
   - The progress cursor itself (whatever store ends up holding it) is
     missing, corrupted, or behind reality — there needs to be an explicit,
     tested recovery path that re-derives truth from the other three
     stores, not just a hope that it never happens.

This deserves real design time before the next refactor touches any of the
gate/reconciliation code again — most of the churn in this session came from
answering this question reactively, one bug at a time, instead of up front.

## Recommended architecture direction: centralize orchestration, minimize agents

A direct response to the pains above, worth taking seriously in the next
refactor rather than incrementally patching the current five-agent design:

- **Only the CTO should assign work.** Right now, assignment is spread
  across multiple agents — the Submitter creates the Reviewer's handoff,
  the Reviewer creates the next part2 Gatherer handoff, and so on. Every
  one of those creation points is another place that has to get Paperclip's
  issue-assignment-wake semantics right (see the `queueIssueAssignmentWakeup`
  behavior above) and another place state can drift or race. Concentrating
  all task/work assignment in one place — the CTO — makes "who starts what,
  and when" something you can reason about by reading one agent's
  instructions, instead of tracing a chain of handoffs through several.
- **Push everything deterministic into scripts, for every agent, not just
  the CTO.** This session's biggest wins were exactly this: dropping sbt
  re-verification in favor of trusting a committed test (a fact, not a
  judgment call), making `LAST.md` a plain fact instead of something an
  LLM computes, and moving the "is this accepted" question to a
  deterministic site-status script instead of agent reasoning. Generalize
  that principle to the whole pipeline: gathering official material,
  verifying a submission's formatting/tests/parity, and submitting an
  answer are all mechanical enough to be scripts with no judgment calls in
  them. **Repeatability** (the actual stated goal — being able to start a
  puzzle's solve from scratch and get the same result) depends on
  minimizing how much of the pipeline is an LLM's one-off decision versus a
  script's reproducible one.
- **Use Paperclip issues/tasks for workflow *state*, not for driving
  behavior.** They're the right tool for "what stage are we in, what's
  blocked, what's rejected" — exactly the one thing from the source-of-truth
  discussion above that only Paperclip's own issue store can answer. They
  should not also be the mechanism that decides *what happens next*; that's
  what centralizing in the CTO (plus deterministic scripts) is for.
- **Only the Solver actually needs to reason.** Gathering official
  material, verifying/submitting an answer, and reviewing a result are all
  candidates for scripting (per above); writing an idiomatic, correct
  solution to a novel puzzle is the one genuinely open-ended, judgment-
  requiring step in the whole pipeline. Treat agent count as a cost, not a
  default — every additional LLM-driven agent is another thing that can be
  woken unexpectedly, another provenance/contract surface, another source
  of nondeterminism.
- **Remove the Solution Reviewer agent.** It's the clearest instance of the
  principle above: this session's entire latency bug existed only because a
  live Reviewer agent got woken to "review" work that a deterministic
  check had already verified. The Reviewer's actual responsibilities —
  validating a result block against the contract, deciding accept/reject,
  advancing the day-to-part2 handoff — are mechanical enough to fold into a
  script the CTO runs directly, with no agent (and no wake-on-assignment
  risk, no provenance-contract trap) involved at all. If something
  genuinely needs human-grade judgment about a rejected attempt, that's a
  CTO (or a repair-specific Solver) decision, not a reason to keep a whole
  review-agent role around for the common case.

## From the Fargate migration and WatchDog/ModelTester removal

- **The custom WatchDog agent was not pure redundancy with Paperclip's
  built-in watchdog — it was a different layer, removed as a deliberate
  simplicity trade-off.** Paperclip has its own run/task watchdog
  (active-run and task-level liveness, bounded event/log reads, per-agent
  cost tracking) — that's infra-level "is this still alive." The custom
  WatchDog agent did *semantic* monitoring on top of that: stall/loop
  detection by comparing repeated action/result pairs across runs. Removing
  it (in favor of relying on Paperclip's native mechanism) traded that
  semantic layer away for simplicity. If a refactor hits repeated-failure or
  stuck-loop patterns that Paperclip's own watchdog doesn't catch (plausible
  given the staged-workspace issues above), this is the capability that was
  given up — worth reconsidering, not assuming it was dead weight.
- **Infra migrations leave residue — check for it explicitly.** After
  deploying the dedicated runtime, a leftover smoke-test container
  (`pcc-aoc-runtime-smoke`) was still running, and a temporary SSH
  client keypair + `known_hosts` file were still sitting in `/tmp`. None of
  this broke anything, but it's easy to forget as "done." Also confirmed
  the old toolchain (Java 25, sbt, asdf shims — about 465 MB) was cleanly
  removable from the controller's EFS once everything ran on the dedicated
  runtime instead; repos, company data, and vault secrets were untouched by
  that cleanup.
- **A locally logged-in Paperclip CLI session is reusable from scripts.**
  `~/.paperclip/{context.json,auth.json}` — the same thing
  `runtime/configure-company.py`'s `Client` class reads — can be reused
  directly by a throwaway script to query the API (e.g. agent
  status/environment binding/secret attachment) without minting any new
  token or asking the user for credentials. This is the same pattern this
  session ended up reusing independently (see "Working with the platform"
  below) — worth formalizing into an actual helper instead of
  reimplementing it ad hoc each time.
- **Credential-hygiene pass before pushing infra changes**: run
  `git diff --check` (catches whitespace issues) and grep the actual diff
  content for anything that looks like a real secret, confirming only
  placeholders (`<public-key>`, `<ECR-repository>`, `<digest>`, etc.) are
  present — done explicitly before committing the Fargate migration, worth
  keeping as a standing step for any future infra-touching commit.

## Upstream Paperclip platform bugs and quirks

These are properties of Paperclip itself (`/home/yoda/Development/Home/paperclip`
locally), not of this package. Re-verify against current Paperclip source if
upstream has since fixed any of them — don't carry a workaround forever once
the root cause is gone.

- **Company hard-delete 500s** with FK ordering violations on
  `heartbeat_runs`/`native_run_finalizations`. Confirmed as a known,
  long-standing, unfixed bug (issue #7250 and ~20 duplicates). Workaround:
  **archive**, never delete, a company you want to retire. Pause its
  routine/disable its trigger first as defense-in-depth.
- **Ephemeral run-scoped `PAPERCLIP_API_KEY` returns 401** for company
  reads/writes under the `ssh`/`legacy-runner` execution shape, and cannot be
  overridden via `adapterConfig.env` (the name is reserved). Confirmed as a
  known upstream gap (issues #21591, #13816). Workaround already shipped in
  this package: mint a **standing agent-scoped key**
  (`paperclipai agent local-cli <agentId> --no-install-skills`), bind it as a
  company secret under a **non-reserved** name (`AOC_PAPERCLIP_API_KEY`), and
  have scripts read that instead. This also means `finish_occurrence`'s own
  HTTP calls were silently 401ing before this fix — which is why occurrence
  issues could get stuck `in_progress` forever even when a "CTO preflight:
  ..." comment had been posted (that comment comes from Paperclip's own
  stdout capture, not from our script's HTTP write).
- **`adapterConfig.env` PATCH replaces the whole map, never merges.** Always
  send the complete desired env, not just the key you're changing.
- **Redacted plain env values round-trip safely.** A GET on an agent shows
  plain env values as the literal string `"***REDACTED***"`. If you PATCH
  back that exact placeholder for a key that already exists, the server
  (`restoreRedactedAgentEnv` in `server/src/routes/agents.ts`) substitutes the
  real stored value instead of overwriting it with the literal string. This
  means you can safely take a GET response, add one new key, and PATCH the
  whole thing back — you never need to know the other keys' real values. Confirmed by reading
  the server source, not just by guessing.
- **Secrets are company-scoped and cannot be cross-referenced.** Reusing one
  company's secret in another 422s ("Secret must belong to same company").
  Every company needs its own secrets created fresh.
- **Environments are instance-wide (name-unique), not company-scoped** — only
  an environment's `privateKeySecretRef` is company-scoped. Repointing a
  shared environment at a new company's secret works but cuts off whichever
  company was using it before. Creating a second environment with the same
  name 409s.
- **Issue-assignment wake behavior is the load-bearing mechanism for "did
  this wake a live agent run."** `queueIssueAssignmentWakeup`
  (`server/src/services/issue-assignment-wakeup.ts`) fires on essentially
  every issue mutation where `assigneeAgentId` is set, **unless** the issue's
  status is already closed (`isClosedIssueStatus`) at the time of that
  mutation, or (on create specifically) the status is `"backlog"`. Concretely:
  - Creating an issue already `status: "done"` never wakes the assignee.
  - Creating an issue `status: "todo"` and then PATCHing it to `"done"`
    **does** wake the assignee on the create — the PATCH is too late.
  - A follow-up PATCH that only adds a comment (status unchanged, already
    closed) does not re-wake anyone.
  This is exactly why the original reconciliation feature's "create as todo,
  then patch to done" pattern caused a live, multi-minute Solution Reviewer
  run on every reconciled part. If you ever need an agent to NOT run live on
  a record you're creating on its behalf, create it already in its terminal
  status in the same call.
- **`POST /api/agents/:id/clear-error` exists but is not exposed by the
  CLI.** Call it directly (reuse `resolveCommandContext`/`PaperclipApiClient`
  from `cli/src/commands/client/common.ts` in a throwaway `tsx` script if you
  need it — see Working with the platform below). Clearing an agent's error
  status often causes it to auto-retry on its own without a fresh manual
  trigger.
- **New agents getting stuck in `verifying`:**
  - `harness_command_unavailable` → missing `defaultEnvironmentId`; imports/
    creates don't set this automatically, PATCH it explicitly.
  - Generic `unclassified` → `cwd` was taken literally during verification
    (e.g. `cwd: /paperclip/workspaces/scala3-aoc` doesn't exist as a literal
    path on a fresh verification target). Root-caused via
    `paperclipai adapter test-environment` (bypasses the lifecycle worker's
    swallowed error). Fix: temporarily set a real `cwd`, let it verify to
    `ready`, then PATCH `cwd` back to the logical path — this does **not**
    re-trigger verification once an agent is already `ready`.
- **Agents can get stuck in a lifecycle transition forever** (e.g.
  `pausing`/`terminating`), where `resume`/`delete` either no-op or 409
  ("Complete termination before deleting the agent"). Never fully
  root-caused this session. Workaround: create a new agent and leave the
  stuck one orphaned (terminated-but-undeleted); don't burn time trying to
  force it through its stuck transition.
- **Company import's `secretValues` never actually gets used two different
  ways:** (a) it always creates brand-new secrets, never matches existing
  ones by name/value, and (b) the `company import` CLI command doesn't even
  send `secretValues` in its request body (confirmed by reading
  `cli/src/commands/client/company.ts`). If you need secrets wired during
  import, call the raw `/api/companies/{id}/imports/apply` (or
  `/api/companies/import`) endpoint directly via a small script reusing the
  CLI's own `resolveInlineSourceFromPath` helper, not the `company import`
  subcommand.
- **`agent.errorReason` / `agentRuntimeState.lastError` are not reliable
  descriptions of the failure.** They appear to be a short, truncated prefix
  of whatever text was captured around the failure — in this session the
  *exact same* string (`"From https://github.com/rolandtritsch/scala3-aoc"`,
  the first line of a successful `git fetch`'s own stderr banner) showed up
  as the stored error for what turned out to be at least two different real
  causes (a stale/empty staged workspace, and genuine git divergence
  elsewhere). **Do not debug from this field alone** — use it only to decide
  *whether* to dig further, then go straight to ECS Exec on the actual
  workspace.

## Staged workspace / EFS issues **(unresolved)**

This is the actual blocker this session ended on, and is worth real
investigation before trusting any daily-selection timing claims in a
refactor.

- Each run gets a workspace directory under
  `/workspaces/agents/.paperclip-runtime/runs/<uuid>/workspace` on the
  runtime's EFS volume. Workspace directories are sometimes **reused**
  across retries of the same occurrence (consistent with the issue's
  `executionWorkspacePreference: "reuse_existing"`), and sometimes a fresh
  occurrence gets a different one — the mapping from run ID to workspace
  directory is not 1:1 and not predictable from the outside.
- Multiple historical workspaces were found with **unpushed local commits**
  left over from earlier Solution Reviewer runs (shared skill/script
  improvements that are supposed to be pushed by "the CTO's next
  synchronization," per the documented workflow, but evidently weren't,
  possibly because the CTO run that should have pushed them crashed first).
  These sat harmlessly until this session pushed `LAST.md` directly to
  `origin/main` from a side-channel local clone — at that point every stale
  workspace with its own unpushed commits became genuinely diverged from
  `origin/main`, and a plain fast-forward pull (which the new gate design
  depends on, to read `LAST.md`) started failing with
  `git merge exited 128: ... Diverging branches ...`.
- Fix attempted: `sync_repo()` in `aoc_cto.py` now pushes outgoing commits
  *before* pulling (`git fetch`, `git push origin HEAD:main`, `git fetch`,
  `git merge --ff-only origin/main`) — this resolves the common case where a
  stale workspace's local commits are a strict ancestor-extension of origin
  (push just succeeds, no force needed). It does **not** resolve genuine
  divergence (independent commits on both sides), which still fails closed
  and needs a human to reconcile.
- At least one workspace was found **completely empty** (no `.git` at all) on
  a retried/coalesced occurrence — staging silently failed with no error
  surfaced anywhere. Never root-caused. Seemed specific to retries, not
  fresh triggers, but that pattern is not confirmed, just observed twice.
- **Lesson for the refactor**: don't assume "the repo checkout a run sees" is
  a single, consistent, always-up-to-date thing. If the gate design depends
  on reading repo state before model inference (as the `LAST.md` redesign
  does), that dependency needs a robust, tested recovery path for a stale
  workspace — not just a bare `git pull`. Consider whether the gate should
  tolerate a workspace that's behind by doing the sync itself with real
  retry/backoff and clear, non-truncated error reporting, or whether
  Paperclip's own workspace-staging behavior needs to be understood/fixed
  upstream first.
- **Side-channel pushes are risky.** Pushing directly to the solution repo
  from a local clone outside of any agent run (as this session did, to
  bootstrap `LAST.md`) is exactly what exposed the above divergence. If you
  need to seed a file like this again, prefer doing it through a real CTO
  run (so its own sync step surfaces and resolves any staleness at the same
  time), or be ready to hunt down every stale workspace afterward.

## Design decisions from the `daily-selection` latency fix

Context: `daily-selection` reconciling an already-solved day was taking
7+ minutes because it woke a live Solution Reviewer that then went on an
unbounded investigation. The fix had two independent layers; keep both if
refactoring this area, they solve different problems:

1. **Don't wake the Reviewer at all for reconciled work.** Create the
   synthetic review issue already `status: "done"` (see the Paperclip quirk
   above) rather than create-as-todo-then-patch.
2. **Make the provenance contract satisfiable for reconciled work.** Added a
   `"reconciled"` provenance status (`aoc_review_contract.py`), distinct from
   `"unknown"`, requiring `verifiedBy`/`siteConfirmed` evidence instead of
   solver logs. Without this, *even if* a Reviewer never runs live, the
   contract's self-check (`verify_review_block.py`, used by the SKILL.md
   "blocking" self-check) would still reject the CTO's own synthetic result
   — so if anything ever does look at one of these issues (manual audit,
   future Paperclip behavior change), it won't spiral into a provenance hunt
   that's structurally impossible to satisfy.

Also decided, per explicit design discussion with the user — worth
preserving the reasoning, not just the outcome:

- **Don't re-run sbt tests to decide "is this already solved."** A committed
  `DayNN.scala`/`DayNNTest.scala` pair with the real-input test marker
  already proves a test passed, because the Solver's publish helper
  (`aoc_solver_publish.py publish`) never lets a commit/push happen
  otherwise. Re-verifying by running sbt again is redundant JVM/compile cost
  for a fact already established at commit time.
- **`LAST.md` (a fact) beats a `NEXT.md` (a decision), as the progress
  cursor.** The agent that would write it (Solution Reviewer) is
  LLM-driven, not deterministic. Recording "what we just finished" needs no
  computation and can't be gotten wrong; computing "what comes next"
  (including year/day rollover) is exactly the kind of logic that should
  live in one pure, unit-tested function (`next_part()` in
  `aoc_cycle_gate.py`), not be re-derived inline by an LLM on every write.
- **The live site (adventofcode.com) is the actual authoritative "is this
  done" signal** — more authoritative than local repo state, and faster
  than re-deriving it (`aoc_site_status.py`, one GET per day, covers both
  parts via the page's own completion markers). This also naturally handles
  drift after a company reimport, where Paperclip's own issue history is
  gone but the site and repo both still reflect reality.
- **A deterministic gate script that depends on repo content needs the repo
  synced *before* it runs, not after.** The original design documented
  "after the gate clears, synchronize main with origin" — fine when the gate
  only reads Paperclip issue history, broken once the gate needs to read
  `LAST.md` from the checkout. `sync_repo()` had to move earlier, into
  `aoc_cto.py::run()`, right before the first gate check.

## Paperclip harness behavior worth remembering

- **Only a specific JSON shape printed to stdout becomes a posted issue
  comment**: `{"type": "text", "part": {"type": "text", "text": "..."}}`.
  A bare `print("some diagnostic")` is captured nowhere visible — not in
  CloudWatch logs (those only have sshd connection logs and generic
  `adapter_failed`/`exit_code_N` summaries, no stdout/stderr body), not as a
  comment. This cost real debugging time: three new failure paths
  (`sync_repo`, `site_complete_check`, `reconcile`) used plain prints at
  first and failed completely silently in production. Always use the
  wrapped shape for anything you want visible after the fact.
- **CloudWatch does not have your script's stdout/stderr.** `/ecs/paperclip`
  has structured HTTP access logs and terse failure summaries
  (`{"errorCode":"adapter_failed","failureCause":"exit_code_2"}`); `/ecs/
  paperclip-aoc-runtime` has sshd connection logs only. To see what a run's
  command actually printed or where it died, you have to either (a) get it
  to post a proper comment (see above) or (b) go inspect the live staged
  workspace directly via ECS Exec.

## Working with the platform — practical playbook

- **ECS Exec interactive sessions are unreliable for large output.** Expect
  `Cannot perform start session: EOF` mid-command on anything producing a
  lot of output (git clone/fetch progress, `git log -p` over multiple
  commits, paged output). Mitigations that worked:
  - Always set `GIT_PAGER=cat` / use `git --no-pager ...` to avoid the
    pager-triggered truncation.
  - Extract one commit at a time with `git format-patch --stdout -1 <sha>`
    rather than a range — ranges over SSM sessions got cut off mid-patch.
  - Strip the SSM banner lines (`Starting session...`, trailing
    `Cannot perform start session: EOF`) and ANSI escape codes
    (`\x1b\[[0-9;]*m`, from git's auto-color even when piped) before trying
    to `git am` a captured patch — uncleaned ANSI codes will corrupt the
    diff and fail to apply.
  - `git` run via ECS Exec executes as a different user than `paperclip`,
    tripping "detected dubious ownership." Set `HOME=/tmp` and
    `git config --global --add safe.directory <path>` per session before
    doing anything else.
- **Recovering stranded local-only commits from a stale workspace**: dump
  each with `git format-patch --stdout -1 <sha>` (one at a time), clean the
  output as above, `git am --3way` it into your own local clone of the same
  repo, then push normally. This is strictly better than `git push` from
  inside the ECS Exec session itself, which has no GitHub credentials
  (`gh auth status` reports logged out there — the real per-run `GH_TOKEN`
  is injected only for orchestrated agent runs, not ad-hoc exec sessions).
- **`coalesce_if_active` routines**: triggering a routine while its previous
  occurrence is still `in_progress` coalesces into that same (possibly
  permanently stuck) occurrence rather than starting fresh. If an occurrence
  is genuinely stuck (agent idle, no further auto-retry, issue still
  `in_progress`), explicitly `paperclipai issue update <id> --status
  cancelled` it before triggering again.
- **Full redeploy cycle for any code change**: rebuild
  (`python3 runtime/publish.py --repository ...`), update the Pulumi
  `aoc_runtime_image` digest, `pulumi up`, then poll
  `aws ecs describe-services ... deployments[?status==PRIMARY].rolloutState`
  until `COMPLETED`. There is no faster inner loop for this runtime; budget
  several minutes per iteration and batch logically-related fixes rather
  than redeploying for each one-line change.
- **Workspace-to-run-ID mapping**: `paperclipai agent runtime-state <id>`
  gives `sessionParamsJson.cwd`, the actual workspace path for the
  *current/last* run — more reliable than trying to guess from `ls -lat` on
  the runs directory, though that's a reasonable fallback.

## What worked well — keep doing this

- Deterministic Python scripts with explicit `except Exception: fail closed`
  blocks, each with a thorough mocked unit test suite (HTTP via injected
  `request`/`opener` fakes, git via injected `run`/`git` fakes). This made
  every behavior change in this session safe to verify in milliseconds
  before ever touching the real deployed system.
- Centralizing the provenance/result-block contract in one module
  (`aoc_review_contract.py`) shared between the CTO's gate and the
  Reviewer's own self-check script (`verify_review_block.py`) — one place to
  add a new status, one set of tests to extend.
- Reusing existing helpers instead of duplicating (`git()` from
  `aoc_existing_solution.py` reused by `aoc_cto.py` rather than
  reimplemented).

## Do-not-repeat list

- Don't push to the solution repo from a side-channel local clone while the
  company is active — see "Side-channel pushes are risky" above.
- Don't trust `agent.errorReason`/`runtime-state.lastError` as a description
  of the actual failure; treat it only as a trigger to go look deeper.
- Don't use `git log -p <range>` or multi-commit `format-patch` over an ECS
  Exec interactive session — do it one commit at a time.
- Don't add a repo-dependent read to a script whose docstring promises
  "no model or Git calls" (`aoc_cycle_gate.py`) without either updating that
  contract deliberately or moving the dependency to a caller that already
  owns repo access (`aoc_cto.py`).
- Don't assume a redacted `"***REDACTED***"` plain env value in a GET means
  you can't safely PATCH the agent — round-tripping it verbatim is exactly
  the supported pattern (server restores the real value).
- Don't assume `paperclipai company import` wires secrets even if you pass
  `secretValues` — it doesn't send them at all; use the raw import-apply API.

[readme]: README.md
