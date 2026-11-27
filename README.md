# AoC Solver - Scala

A four-role Paperclip company solving Advent of Code 2015–2025 in Scala 3.
The CTO authorizes one day at 06:00 UTC. Gatherer, Solver, and Submitter
execute its stages, with accepted part1 continuing to part2. Another day or
repair waits for the next daily or explicit manual check.

The Solver works from first principles. There is no Reviewer, source audit,
or algorithm assessment. Completion requires mechanical verification and
authenticated site acceptance; it does not claim audited independence.

## Solver model history

| Puzzle days | Solver model |
| --- | --- |
| 2015 Day 01–16 | DeepSeek (`openrouter/deepseek/deepseek-v4-pro-0813`) |
| 2015 Day 17–25 | NVIDIA Nemotron 3 Ultra (`openrouter/nvidia/nemotron-3-ultra-550b-a55b:free`) |
| 2016 Day 01–12 | Kimi K3.1 Pro (`openrouter/moonshotai/kimi-k3.1-pro`) |
| 2016 Day 13 (initial attempts) | Particle-1 (`openrouter/particle-ai/particle-1:free`) |
| 2016 Day 13 onward | ERNIE 5.5 Flash Preview (`openrouter/baidu/ernie-5.5-flash-preview:free`) |

## Architecture

[DESIGN.md][] records the decisions, authority boundaries, restart behavior,
and qualification requirements. Company code is imported as complete managed
skill resources. The dedicated Fargate image supplies only tools and a small
launcher. Solution workspaces sit outside Paperclip's SSH staging/restoration
tree; published Git commits and AoC evidence survive company replacement.

## Operator commands

```bash
python3 operators/aoc.py --help
python3 operators/aoc.py diagnose
python3 operators/aoc.py package --package /tmp/aoc-package.json
python3 operators/aoc.py deploy plan --company COMPANY --package /tmp/aoc-package.json --record /tmp/aoc-deploy.json
```

Read [operator procedures][operations] before apply, activation, or recovery.
The API wrapper includes executable helper files that the existing CLI package
collector omits. Imports stay paused; deployment success alone does not prove
runtime readiness. Rollback uses a saved package, not an unpinned branch.

Install the five local operator skills with:

```bash
python3 operators/aoc.py install
```

Canonical skill sources are versioned here. They are excluded from company
imports and do not grant company agents deployment permissions.

## Verify changes

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q operators skills/aoc-runtime/scripts runtime
```

Tests exercise actual temporary Git remotes, stage restart/idempotency,
account-aware parsing, receipt binding, imported release checksums, and
submission uncertainty. Production rollout, actual SSH helper delivery,
real template tests, and destructive recovery have separate qualification
requirements. Historical reports are evidence about earlier versions.

[DESIGN.md]: DESIGN.md
[operations]: operators/OPERATIONS.md
