---
name: aoc-solve-scala
description: Solve and publish an assigned Scala puzzle from first principles
---

Use the complete imported [aoc-runtime][] release. The launcher performs
mechanical stages; only Solver runs model reasoning.

Derive the assigned solution from official rules, examples, and personal input.
Do not obtain existing puzzle implementations, editorials, walkthroughs, or answers
from the web, local repositories, or another agent. Preserve other working parts.

Code quality/convention authority: `scala3-aoc/AGENTS.md` in the solution checkout.
This skill does not restate it — read it before writing any solution file.

Publish only through:
`python3 "$AOC_RUNTIME_DIR/scripts/entry.py" publish --answer ANSWER --files PATH ...`
The helper formats, executes assigned-day/full-year tests, checks exact runner
output, commits allowed files, pushes, verifies remote state, and records the result.
A successful solve without this publication is incomplete. On failure preserve work
and record the actual blocker; do not guess another answer or change the workflow.

[aoc-runtime]: ../aoc-runtime/SKILL.md
