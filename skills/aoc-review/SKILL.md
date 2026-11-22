---
name: aoc-review
description: Review AoC submission evidence and improve future work through tested, committed project-local skills and scripts, and continue only accepted part1 within its authorized day
---

Follow `aoc-workflow`. You receive final accepted/rejected attempts from submitter
or historical accepted work from CTO. Read [the research][research] for design
rationale and limits; use the checkout's `AGENTS.md`, applicable local skills,
and prior review findings for the actual review.

A review issue that is already `status: done`, carrying a CTO-authored
`aoc-review-result` with `provenance.status: "reconciled"`, is a closed
historical record, not a live submission: the CTO already confirmed it
against the authenticated adventofcode.com page before creating it. Take no
action — do not reopen it, do not reconstruct tool logs for it, and do not
inspect other agents' or runs' history looking for its provenance. It was
never assigned to you as work to audit.

## Provenance check

Inspect the solver's declared sources and the complete available run/tool log,
including shell commands, fetched URLs, file reads and invoked helpers. Check
that gatherer supplied official material rather than third-party explanations
or known personal answers. Verify a concise derivation/invariant, complexity,
sample/boundary tests and an independent check. Do not require a private
reasoning transcript; assess the supplied algorithm justification and evidence.

Look specifically for existing puzzle solutions, editorials, walkthroughs,
answer lists, unrelated local/remote solution repositories or delegated lookup.
Generic technical docs, template/utilities, dependency downloads and required
Git/Paperclip calls are allowed. Record sources, the logs inspected and their
coverage in the review. Record every solver attempt run ID, complete log byte
count and tool-call count, the allowed sources and an explicit provenance
verdict. A handoff, Git reflog or absence of a search in those artifacts cannot
replace the tool-log audit. Missing/truncated logs mean `unknown`; disallowed
material means `contaminated`. Neither clears accepted advancement. State only what those observations
support; they do not
reveal a model's prior training. Missing logs or provenance evidence block a
provenance clearance. Disallowed solution use requires a CTO decision about a
fresh independently derived attempt, even if the answer is accepted.

## Review and learn

1. Inspect the assigned part's statement, source, tests, git changes/history,
   solver command results, and original submission verdict. For the finale,
   inspect actual site prerequisites and completion evidence instead of
   requiring a computational implementation. Missing required evidence is a
   blocker with an owner and action, not a reason to invent a verdict.
2. Explain **what worked, what did not, why not, whether we can fix it, and how**.
   Separate observed facts, hypotheses, and missing information. An accepted
   answer does not prove every boundary case is correct. A rejected answer is
   not explained until there is evidence for the proposed cause.
3. Before creating a helper, inspect the bundled skill scripts and existing
   checkout helpers. Use `$AOC_COMPANY_PACKAGE_DIR/skills/aoc-review/scripts/verify_review_evidence.py
   --year YYYY --day NN --part P --answer ANSWER --commit FULL_SHA` for mechanical
   verification before making improvements. This delegates to the existing
   publication helper's **verify** mode, including formatting, active assigned-day
   tests, exact runner answer, and clean HEAD/tracking/live-remote parity both
   before and after checks. It never publishes or creates a task. For a finale,
   use the authenticated prerequisite/completion evidence instead. Do not create
   another validator or evidence checker. An installed compatibility wrapper in
   scala3-aoc must delegate to the bundled helper rather than duplicate it.
   Compare with previous reviews: identify repeated manual work, repeated errors,
   reusable problem-solving techniques, and existing skills/scripts worth reusing.
   Distill a skill when a validated technique has a clear reusable trigger;
   extend an existing skill rather than duplicating it. Build a script when
   repeated mechanical work benefits from deterministic inputs and outputs.
4. Choose a small evidence-backed improvement and make **one improvement pass**.
   It is valid to make no change if nothing useful is demonstrated. Unfinished
   or speculative work stays in the report for a later CTO decision. Do not
   spawn improvement tasks or repeatedly refine your own review.
5. Put all newly distilled skills and scripts in **scala3-aoc**, never in
   this company package, a personal skill store, or Codex memory:
   - `skills/<descriptive-name>/SKILL.md` with `name`, `description`, clear trigger,
     inputs, procedure, evidence/validation, and stopping conditions.
   - Reusable executables in `scripts/`; supporting skill references may live
     beneath its skill directory. Keep behavior-specific guidance concise.
   - Update project `AGENTS.md` with discovery/use instructions where necessary.
     Do not edit generated guidance if the repository has a source workflow.
6. Validate before adoption. Exercise scripts on fixtures or safe read-only
   inputs, including their relevant failure cases; do not submit answers or
   create live tasks just to test a helper. Validate skill frontmatter, links,
   and a realistic use case. Run relevant repository checks when changes affect
   the build or solutions. Do not weaken assertions, skip tests, or change known
   expected answers to make an improvement appear successful.
7. Inspect the diff and unrelated changes, check whitespace, and **commit** only
   validated improvement files in scala3-aoc with a focused message such as
   `Review DayNN part P: <improvement>`. Commit does not authorize push. If
   validation fails, revert only your failed improvement, record the failure,
   and retain the existing workflow. Puzzle-answer repairs remain solver work
   authorized by a later CTO wake-up.

## Durable report and stop

Publish the report in the review issue's comment or document before disposition:

- Year/day/part, attempt, verdict, reviewed solution commit, and upstream links.
- What worked; what failed; supported root cause or explicitly labeled hypotheses.
- Can it be fixed, how, and which puzzle repair remains for the CTO/solver.
- Reusable lessons, repeated work, skill/script changes or reasons for no change.
- Improvement file paths, commit hashes, validation evidence, and adoption limits.
- Next CTO recommendation, including any unresolved repair or evidence gap.

Also write this fenced JSON in the final review comment (use actual values):

```aoc-review-result
{"reviewIssueId":"<current issue UUID>","year":2015,"day":1,"part":1,"solutionCommit":"<full reviewed commit>","accepted":true,"repairRequired":false,"provenance":{"status":"clear","sources":["official statement/input and allowed utilities"],"solverRuns":[{"runId":"<solver run UUID>","logBytes":12345,"toolCalls":12,"complete":true}]}}
```

Set `accepted` only from authoritative site evidence; record `repairRequired`
for an unresolved rejection/defect. A `done` status alone cannot clear the CTO
gate. An unfinished review or failed final status write keeps the cycle waiting.

On an accepted part (part1 continuing within the day, or part2 ending it),
also write and commit `LAST.md` at the `scala3-aoc` root with the part just
accepted, e.g. `{"year": 2015, "day": 4, "part": 2}` inside a fenced
` ```aoc-last ` block — this is the fact `aoc_cycle_gate.py`'s `next_part()`
advances from. Record only the fact just accepted; never compute or guess
the following part yourself.

### Result-block self-check (blocking)

A review without a valid result block is defective and stalls the whole
cycle: on 2026-10-15 a prose-only accepted review held up advancement for
5 hours because the gate could not clear it. Before marking the
review `done`:

1. Confirm the final comment carries the fenced block with actual values,
   never the `<...>` placeholders.
2. Fetch this issue's full JSON from the API into run scratch (including its
   description and the submitter's unchanged `aoc-solver-publication` receipt).
   Run `python3 $AOC_COMPANY_PACKAGE_DIR/skills/aoc-review/scripts/verify_review_block.py
   --issue-file /path/to/scratch/issue.json --body-file /path/to/scratch/report.md`.
   Use the deployed company package path from `AOC_COMPANY_PACKAGE_DIR`.
   Runtime skill-loader directories may contain only SKILL.md, without scripts.
   Do not recreate this script in the solution checkout.
   It exits non-zero for identity/commit mismatches or missing provenance coverage.
   Reviewer's result and title alone cannot establish the expected commit.
   This validates audit declarations; the reviewer must actually inspect logs.
   A noncomputational finale uses the submitter's `aoc-review-context` with
   `kind: finale`, full `solutionCommit`, and provenance `status: not_applicable`
   with an explicit reason. Never exempt a computational part.
3. Mark `done` only on exit 0. A failing check keeps the review open and
   recorded — never mark a block-less review `done`.

Mark the review `done` when its report, any chosen validated improvements,
and the passing result-block self-check are complete. A rejection review may finish with a recorded pending solver repair;
that part is not complete. Missing required evidence keeps the review `blocked`.
For accepted part1 only, create/reuse a same-year/day part2 gatherer issue
with the inherited day authorization. Stage it in backlog, persist the passing
result block and mark this review done, then activate the confirmed handoff
as todo. On interruption, reconcile that same issue; never create duplicates.
Accepted part2 and rejected attempts have no downstream handoff and wait for
the next daily CTO check. Never start another day, wake CTO or enable timers.

[research]: references/recursive-self-improvement.md

Use explicit year-qualified issue identity and paths throughout. Run sbt in
`YYYY/`; Git and shared skills remain at the scala3-aoc root.
