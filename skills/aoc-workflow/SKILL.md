---
name: aoc-workflow
description: Coordinate all AoC 2015–2025 parts with daily 06:00 UTC readiness checks, year-aware evidence, and duplicate-safe handoffs
---

## Scope and day authorization

Solve every part of every day in years 2015–2025, ordered by year, day, part.
2015–2024 each have 25 days; 2025 has 12. This is 262 days and 524 parts.
Day00 and year 0000 are templates, excluded from progress. Never invent 2025
Day13 or work outside these years. Final-day part2 (Day25 in 2015–2024,
Day12 in 2025) follows the authenticated site's completion interaction.

The CTO checks once daily at 06:00 UTC through the daily-selection routine
(`0 6 * * *`), an hour after AoC's midnight-EST puzzle release, with interval
heartbeats disabled. When the gate is clear,
it authorizes at most one day, both parts sequentially, or the current day's
repair. Manual board triggers can explicitly request a check. No specialist
wakes the CTO.
CTO routine occurrences are outside puzzle stages.

The cycle is gather → solve → submit → review for each computational part.
Only after authoritative acceptance and a successful completed part1 review
may reviewer create/reuse that same authorized day's part2 gather issue.
Stage the verified part2 handoff in backlog before marking part1 review
done, then activate it as todo. Reconcile this same handoff on interruption. Keep the original day
authorization identity through both parts. Accepted part2 ends the day.
Rejected attempts are reviewed, then wait for a later CTO readiness check
before repair selection. No specialist creates another day or retries rejected
code itself.

## Independent solving and provenance

All puzzle implementations must be derived from the official rules, examples
and personal input, with concise algorithmic justification and independent
checks. Do not obtain existing solutions, editorials, walkthroughs or answers
from the web, other repositories or another agent. Do not seed solver handoffs
with historical personal answers. Existing acceptance is checked by submitter
after the answer has been independently derived and verified.

Template code, generic utilities, general algorithms and generic technical
documentation are allowed; an existing implementation of the assigned puzzle
is not. Gatherer supplies official material only. Solver records sources used
and its algorithm/invariant, complexity and verification evidence. Reviewer
checks provenance against complete available tool logs, not just the agent's
claim or an accepted answer. Record missing evidence as unknown, not as proof
of independent solving. Report disallowed material to CTO; do not pass the
provenance check merely because tests or submission succeed.

## Year layout and bootstrap

`AOC_REPO_DIR` is the canonical Git root of rolandtritsch/scala3-aoc, not a
year's sbt directory. Each handoff carries `year`, day, part, stage, root,
`AOC_CYCLE_STARTED_AT`, day authorization/source issue, decision commit,
solution commit, answers, tests and verdicts when available. Titles use
`AoC YYYY DayNN partP: stage`; NN is zero-padded in paths, unpadded in URLs.
Review attempts also include their solution commit to avoid verdict reuse.

Read root `AGENTS.md`, `README.md` and applicable root `skills/*/SKILL.md`.
For an absent selected year, copy `0000/` to `YYYY/` excluding `target/`,
`project/project/`, `.bsp/`, `.bloop/` and `.metals/`. Rename `aoc0000` source
and test directories and package references to `aocYYYY`; update the sbt
project name and year CI matrix. Preserve Day00, the template and all existing
years. Never overwrite an existing year. Format, compile, execute tests and
run Day00 in the new year; commit only bootstrap and CI files separately.
Then continue with the authorized day. Bootstrap must be complete before the
solver publication helper, which accepts only intended puzzle paths.

Statements live at `YYYY/problems/DayNNProblem.txt`; sources/tests use
`YYYY/src/{main,test}/scala/aocYYYY/`; resources use
`YYYY/src/main/resources/inputs/`. Run every sbt command inside `YYYY/`.
Use `sbt --batch run` and `sbt --batch 'testOnly *'` (not a thin-client
`test` invocation that can execute zero tests). Git operations use the root.
Shared reviewer improvements live in root `skills/` and `scripts/`, with
root AGENTS.md discovery guidance; year-specific artifacts stay in YYYY.

## Gate and evidence

The CTO launcher runs `scripts/aoc_cycle_gate.py` before inference. For `wait` or `complete`, the launcher records the decision
and marks its owned coordination task done before exiting; a failed status
write fails the run. Unknown evidence fails closed without completing the task. CTO also
checks it before selecting and immediately before creating work. It is
read-only, paginated, bounded, year-aware and fail-closed. Current-cycle
specialist tasks at or after `AOC_CYCLE_STARTED_AT` gate progress. Unfinished
stages, missing successful review, live specialists or ambiguous evidence
mean wait. Rejected reviews permit only the same year/day/part repair.
Completed acceptance requires a full commit matching the submitter's publication
receipt in the review description and explicit complete solver-log provenance
coverage. Title matching alone is insufficient. The self-check and this gate
share `scripts/aoc_review_contract.py`. A matching result looks like:

```aoc-review-result
{"reviewIssueId":"actual UUID","year":2015,"day":1,"part":1,"solutionCommit":"actual full hash","accepted":true,"repairRequired":false,"provenance":{"status":"clear","sources":["official statement/input"],"solverRuns":[{"runId":"actual UUID","logBytes":12345,"toolCalls":12,"complete":true}]}}
```

All 524 accepted completed reviews with no open specialist work yield
`complete`. A completed year alone does not finish the company. Old cycle
tasks are context only; never reset history to make current work look complete.

After the gate clears, synchronize main with origin: fetch, fast-forward pull,
push outgoing commits, prove a clean tree and HEAD/tracking/live-remote
equality. Dirty/diverged work and auth failures block selection. Never discard
another agent's files or force-push. Current year-project runner and executed
tests select the earliest unfinished computational part. Historical tickets,
filenames, site acceptance and stored answers do not substitute for code
verification. Preserve site acceptances and reconcile them read-only rather
than submitting an accepted answer again. Finale acceptance uses site evidence.

## Publication and handoffs

Gatherer commits intended material in the canonical checkout. Solver must use
`aoc-solve-scala/scripts/aoc_solver_publish.py publish --year YYYY` to format,
verify tests and exact runner answer, commit only intended files, push and
prove remote parity before creating/reusing submitter work. Submitter runs
`verify --year YYYY` independently before site interaction. Failed checks block
the part. Do not bypass publication through manual API/Git handoffs.

Reviewer validates and commits useful root skills/scripts in scala3-aoc.
CTO's next synchronization or the next authorized publication pushes these
commits. All agents read relevant local skills and prior review findings.
Use injected GitHub auth (`gh auth setup-git` when needed), never tokens in
URLs or files. Never print credentials or dump the environment.

Use the runtime Paperclip skill for task checkout and authentication. Resolve
recipients by exact names: Problem Gatherer, Problem Solver, Problem Submitter,
Solution Reviewer. Read all relevant issue pages, descriptions and comments.
Match current cycle, authorization, year, day, part and stage; reviews also
match attempt/commit. Reuse existing active work including blocked work;
reconcile ambiguous POST acknowledgements before retrying. Never hard-code
company/agent UUIDs. Ordinary handoffs create top-level issues with
`parentId: null`, verify the returned assignment/description, then mark the
source done with result/evidence/downstream link. Solver handoffs exclusively
use its helper; reviewer has only the accepted-part1 continuation described
above. All other review outcomes have no downstream task.

Use `Authorization: Bearer $PAPERCLIP_API_KEY`, injected
`PAPERCLIP_API_URL`/`PAPERCLIP_COMPANY_ID`, and
`X-Paperclip-Run-Id: $PAPERCLIP_RUN_ID` plus JSON Content-Type on mutations.
Mark blocked work with exact evidence gap, owner and unblock action using
`unblockDescriptor` or an actual blocker link. A comment alone is not a final
status. On a 409 ownership conflict stop and report; do not retry or compete.

A review must persist its report and validated result block. For accepted
part1, also verify the same-day part2 handoff; then mark review done. If status
persistence or handoff fails, keep the review unfinished and reconcile on
resume. Part2 stays in backlog until part1's review is successfully completed,
then reviewer activates it; gatherer independently checks that prerequisite.
Once part2 is accepted/reviewed, stop until the next CTO readiness check.
