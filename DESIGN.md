# Restartable AoC company

## Decisions

Agreed November 22, 2026. Keep CTO, Gatherer, Solver, and Submitter. Remove
Reviewer, source auditing, and algorithm assessment. Keep the Solver's
first-principles instruction; do not claim independently audited provenance.
Authorize one day at 06:00 UTC, with sequential parts and no interval
heartbeats. Failed attempts wait for another daily or manual authorization.

Use the dedicated Fargate SSH runtime. Import company code separately from
the tools image through a board-authenticated API wrapper. Do not add S3 or
modify Paperclip. Canonical operator skills live in this repository and are
linked into local Codex discovery, never imported into the company.

## Authority and durability

| Fact | Authority |
| --- | --- |
| Published code/material | GitHub commit |
| Acceptance and accepted answer | Recognized, authenticated AoC page |
| Current authorization/stage | Current company's Paperclip documents/tasks |
| Execution files | Disposable runtime checkout |

`.aoc/progress.json` in the solution repository stores versioned per-part
completion records bound to account, solution commit, verification hashes,
and site evidence. It replaces `LAST.md`. A corrupt index blocks ordinary
execution and requires explicit reconstruction. Missing entries are recovered
by verifying existing committed solutions against authenticated accepted
answers. A missing index starts reconciliation at the first configured part.
Historical reconciliation is not a source audit.

Only published solutions must survive destructive resets. Unfinished work and
Paperclip history may be lost. Backups used for instance restoration must pair
the database with its encrypted-vault master key. A fresh reset instead needs
credentials provisioned again. No token, cookie, private key, or raw input is
included in release records or operation journals.

## Execution

The CTO's deterministic engine alone assigns stages. A stage identity includes
company generation, authorization, year/day/part, stage, and attempt. Task
creation uses idempotency keys; mutable documents use base-revision checks.
Specialists persist a result, finish their task, and notify the CTO's control
task. Continuation can finish the authorized day but cannot select another.

Stages are gather, solve, submit, accepted; verification is a mandatory helper
inside solve/publication and submission. Failures distinguish rejected,
blocked, and uncertain. Persist submission intent before POST. A lost response
is uncertain and must reconcile against the site before any further POST.
Explicit rate limits permit two retries, respecting the server delay. Read
requests use three bounded attempts; identity/authentication/Git conflicts
stop immediately. The noncomputational final part is a separate site-driven
interaction with prerequisite checks, never an invented answer.

Paperclip stages a dispatch directory and its selected managed runtime skill.
The image launcher verifies the imported release manifest and starts its
entry point. Solution checkouts are outside the staged/restored tree. Each
attempt starts from verified remote main; unexpected local work is preserved
and blocks reuse. No automatic arbitrary outgoing-commit push or force push.

A runtime-wide file lock serializes mutations. `.aoc/owner.json` binds the
repository to one company generation. Every publication and submission
checks the live owner. Replacement drains old runs before ownership transfer;
old credentials are retired. A shared runtime lock is not a distributed lock
across independently provisioned runtimes; operators must not activate two
runtime services for the same solution repository.

Build helpers run foreground `sbt --server` with a short IPC directory, avoiding
Paperclip's long XDG paths and persistent thin-client server processes. Live
private diagnostics remain readable during builds; raw stderr is not posted.

Verification requires formatting, positive executed assigned-day tests, full
year tests via `testOnly *`, and exactly one answer for the assigned part.
Receipts identify the solution commit and relevant year/input/build hashes.
Later progress commits may advance main: verify ancestry and relevant hashes,
not obsolete equality of solution commit and current HEAD.

## Releases and operations

The import wrapper packages an explicit allowlist and submits complete helper
files, bypassing the CLI's Markdown-oriented collector. Use the global
board-authorized import API for replacement: company-scoped safe imports
reject replace collisions. Preview, apply paused, reconcile bindings, and
read back skills/configuration before activation. Staged secret declarations
are optional at import because agent keys cannot exist before agent creation;
the operator readiness gate requires real bindings. Existing instruction entries
are reconciled through the canonical revision API, and routines are reconciled
separately to avoid duplicate imports. Rollback imports an earlier
saved package. Supporting files are Python-interpreted, not chmod-dependent.

The complete runtime skill also carries the pinned `0000` template and initial
CI workflow for empty-repository recovery. Its source revision is recorded in
`assets/template-source.json`; do not copy puzzle solutions into that bundle.

The tools image contains the pinned toolchain and a small versioned launcher,
not company helpers. Tools changes publish an immutable digest; ordinary
company-code fixes only import. A release record binds package commit/hash,
tools digest, controller image, and launcher compatibility. Dirty source
releases are identifiable and cannot be mistaken for committed releases.

Operator commands share plan/apply/verify and private resumable journals:

| Operation | Boundary |
| --- | --- |
| Diagnose | Read source/import/image/storage/task state |
| Deploy | Import complete company package, preserve identity |
| Replace company | Pause triggers/agents, drain, prepare replacement, rebind, transfer ownership, archive old company |
| Deploy tools | Build/publish digest, preview/apply Pulumi, wait for real rollout |
| Recover | Resume results, quarantine workspaces, or prepare an explicit storage/instance reset |

Destructive reset plans enumerate resources and other companies. Approval
must name the concrete reset. Never automatically escalate a workspace fix
to EFS/database replacement. Runtime EFS replacement loses host identity and
requires authenticated repinning. Controller EFS/database operations affect
the whole instance and must preserve or deliberately replace vault identity.

## Qualification and rollout

1. Exercise import resource delivery, schema contracts, and isolated Git
   workspaces locally; test real crash boundaries and duplicate continuation.
2. Test empty/existing repositories, missing/corrupt index, account mismatch,
   changed code, dirty/diverged work, rejected and ambiguous submissions.
3. Preview a paused replacement company. Verify exact four-role roster,
   per-agent credentials/environment, one 06:00 UTC trigger, and zero runs.
4. Build the new launcher image once; verify ECS completion, actual task
   digest, SSH host identity, imported helper hashes, and real template tests.
5. Reconcile existing solutions, cut over ownership, then enable the schedule.
6. Demonstrate tools rollback and company-only rollback. Qualify full reset
   and fresh bootstrap in a disposable stack, never production by default.

Measure normal selection separately from cold start and reconciliation; target
under one minute for ordinary no-build selection. Local tests do not establish
live timing, live delivery, or successful disaster recovery. Track unexecuted
qualification explicitly in the release record.
