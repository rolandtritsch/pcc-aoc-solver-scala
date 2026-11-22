# AoC Solver - Scala

A four-role Paperclip company solving Advent of Code 2015–2025 in Scala 3.
The CTO authorizes one day at 06:00 UTC. Gatherer, Solver, and Submitter
execute its stages, with accepted part1 continuing to part2. Another day or
repair waits for the next daily or explicit manual check.

The Solver works from first principles. There is no Reviewer, source audit,
or algorithm assessment. Completion requires mechanical verification and
authenticated site acceptance; it does not claim audited independence.

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
