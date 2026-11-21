# AoC Solver - Scala

A Paperclip company that solves every part of [Advent of Code][aoc] from
2015 through 2025 and publishes solutions to [rolandtritsch/scala3-aoc][repo].
It covers 262 days and 524 parts: 25 days per year for 2015–2024 and 12 for
2025, including the authenticated final completion interactions.

## Daily workflow

The [daily selection task][daily] is the single trigger for readiness checks:
a native routine assigned to the CTO, scheduled `*/2 * * * *` with
`skip_missed` catch-up and `coalesce_if_active` concurrency. The CTO's own
interval heartbeat stays disabled so this routine is the only thing waking it.

Order is year, day, then part, beginning at 2015 Day01 and ending at 2025
Day12. Each selection authorizes one day. Work proceeds through gather → solve
→ submit → review for part1, then the reviewer hands accepted part1 to the
part2 gatherer within the same authorized day. Accepted part2 ends the day.
A rejected attempt is reviewed and waits for a CTO readiness check before
repair authorization.
Specialists never start another day or wake the CTO. The CTO exits if any
current day stage or review is unfinished. Verified existing site acceptances
are preserved; current code still requires executed tests and runner evidence.

| Agent | Responsibility |
| --- | --- |
| CTO | Selects one year/day or repair when the cycle gate is clear |
| Problem Gatherer | Assigned-year statements and cached personal input |
| Problem Solver | Idiomatic Scala 3, active tests, verified commit and push |
| Problem Submitter | Verify publication, submit or reconcile authoritative acceptance |
| Solution Reviewer | Review each verdict, improve reusable skills, continue accepted part1 to part2 |

Agent/run health and liveness are monitored by Paperclip's native watchdog
mechanisms; this package does not ship its own observer agent.

## Independent solving

Solutions must be derived from the official puzzle rules, examples and personal
input. Existing solutions, editorials, walkthroughs and answer lookups are
prohibited, including indirect lookup by another agent or another local repo.
Generic algorithms, template utilities and technical documentation are allowed.
Each handoff records a concise algorithm explanation, independent checks and
sources used; reviewer checks the complete available tool log for provenance.

The [first-principles audit][originality-audit] records the initial part1 run.
This is an instruction and audit policy, not a claim of network isolation or
knowledge of the model's training history.

## Solution layout

`AOC_REPO_DIR` is the Git root of `rolandtritsch/scala3-aoc` on branch `main`.
Every handoff includes explicit `year`, day, part, stage, cycle start, root,
year-project path, authorization issue and solution commit. Issue titles use
`AoC YYYY DayNN partP: stage`; review result JSON includes `year`.

- `0000/` remains the reusable template. Never solve real puzzles there.
- `YYYY/` is an independent sbt project, package `aocYYYY`.
- Statements: `YYYY/problems/DayNNProblem.txt`.
- Sources: `YYYY/src/main/scala/aocYYYY/DayNN.scala`.
- Tests: `YYYY/src/test/scala/aocYYYY/DayNNTest.scala`.
- Inputs: `YYYY/src/main/resources/inputs/DayNN.txt`.
- Shared improvements: root `skills/` and `scripts/`.

When the selected year is absent, copy `0000/` excluding generated artifacts,
rename source/test packages from `aoc0000` to `aocYYYY`, update `build.sbt`,
and add the year to the CI matrix. Preserve Day00 and existing year projects.
Validate and commit this bootstrap separately before gathering/solving. See the
solution repository's `README.md` and `AGENTS.md` for the copy command and checks.
Run sbt **inside `YYYY/`**, while Git synchronization and commits use the root.
Use `sbt --batch run` and `sbt --batch 'testOnly *'`; the template's pinned
thin client can turn `test` into `testQuick` and execute zero tests.

The [workflow][workflow] defines gates and handoffs. The [solver helper][solver]
requires `--year YYYY`, checks intended year-prefixed paths, runs builds in
that year, verifies exact textual answers (including negative/text answers),
pushes, and proves HEAD/tracking/live-remote parity before handoff. Final-day
noncomputational interactions use authenticated evidence instead.

## Import and deployment

This is a new company package derived from `pcc-aoc-solver-2025-scala`.
The source revision is `17892a8635442c7feb6570f276dad7a183185395`.
The original package and running company are independent. The bundled
company-creator skill and research references retain their original attribution
and historical context; current operating rules are in this package's agent
instructions and AoC skills.

```bash
paperclipai company import . --target new --dry-run
paperclipai company import . --target new
```

The package explicitly selects `adapter.runner: legacy` for OpenCode. The
current Paperclip Runner rejects custom `command` launchers, which the CTO
requires. Preserve this choice when importing. The CTO launcher
allows only Paperclip's exact credential-free `Respond with hello.` verification
prompt during setup; authenticated puzzle runs still require the cycle gate.

Include tasks/routines in the import. Indent schedule trigger list items beneath `triggers:`; the portability
parser silently drops indentationless YAML lists. Inspect the preview for the CTO-owned
`daily-selection` routine, cron `*/2 * * * *`, timezone `Europe/Dublin`, and
active status. Some import modes pause automations: after deployment verify
and activate this routine, with the CTO runnable and its interval heartbeat off.
This repository alone does not deploy a company or activate a live schedule.
Do not replace the old company or reuse its cycle timestamp or deployment IDs.

Agents run in a dedicated execution environment with the prepared image in
`runtime/`. Java, sbt, OpenCode, Git, GitHub CLI, and Python are installed in
that image; they do not depend on tools in the controller's EFS volume.
See [runtime deployment][runtime] for build, verification, and company binding.

`cwd: /paperclip/workspaces/scala3-aoc` identifies the controller-side source
checkout. Paperclip stages it into the SSH environment and restores work after
each run. The runtime launcher sets `AOC_REPO_DIR` to the staged directory and
uses company helpers baked into `/opt/aoc-company`. It prepares the known GitHub
remote and `main` branch for the company's explicit publication workflow.

Configure `AOC_CYCLE_STARTED_AT` to the new company's activation instant; the
placeholder `SET_AT_DEPLOYMENT` fails closed until configured. Confirm the
solution checkout exists, has the correct origin and clean main branch, and
contains `0000/` before activating the routine. Bind every agent to the dedicated
environment; importing the package alone does not create or assign it.

Bind vault-backed `OPENROUTER_API_KEY`, `AOC_SESSION` (gatherer/submitter), and
GitHub authentication for agents publishing solutions. Never copy credentials
into the package. Existing Pro/Flash model pins and OpenRouter mappings are
inherited configuration, not a fresh model evaluation. Read before changing
provider bindings. Reviewer commits shared improvements; the next authorized
publication or CTO synchronization pushes them.

## Verification

Run from this package's root:

```bash
python3 -B -m unittest discover -s skills/aoc-workflow/scripts/tests -v
python3 -B -m unittest discover -s skills/aoc-solve-scala/scripts/tests -v
python3 -B -m unittest discover -s skills/aoc-review/scripts/tests -v
```

The gate distinguishes identical day/part numbers across years, requires
matching year-qualified review results, and stops after all 524 accepted
reviews. It never invents 2025 Day13 or 2026 work. Missing evidence fails closed. Review results bind to the submitter's full
publication receipt and require explicit complete solver-log provenance coverage.
The reviewer uses bundled validators under `$AOC_COMPANY_PACKAGE_DIR`; mechanical
checks reuse the publication verifier. A waiting daily check records its decision
and completes its occurrence without starting more puzzle work.

[aoc]: https://adventofcode.com/events
[repo]: https://github.com/rolandtritsch/scala3-aoc
[daily]: tasks/daily-selection/TASK.md
[workflow]: skills/aoc-workflow/SKILL.md
[solver]: skills/aoc-solve-scala/SKILL.md

[originality-audit]: reports/2026-11-19-first-principles-audit.md

[runtime]: runtime/README.md
