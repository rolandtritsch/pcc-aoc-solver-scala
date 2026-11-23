---
name: aoc-solve-scala
description: Solve and publish an assigned Scala puzzle from first principles
---

Use the complete imported [aoc-runtime][] release. The launcher performs
mechanical stages; only Solver runs model reasoning.

Derive the assigned solution from official rules, examples, and personal input.
Do not obtain existing puzzle implementations, editorials, walkthroughs, or answers
from the web, local repositories, or another agent. Preserve other working parts.
Write idiomatic Scala 3 with ScalaDoc and meaningful sample/boundary/real-input tests.
Run Git at repository root and sbt inside the assigned independent YYYY project.
Publish only through:
`python3 "$AOC_RUNTIME_DIR/scripts/entry.py" publish --answer ANSWER --files PATH ...`
The helper formats, executes assigned-day/full-year tests, checks exact runner
output, commits allowed files, pushes, verifies remote state, and records the result.
A successful solve without this publication is incomplete. On failure preserve work
and record the actual blocker; do not guess another answer or change the workflow.

[aoc-runtime]: ../aoc-runtime/SKILL.md

Follow the solution repository AGENTS.md: use per-day `aocYYYY.dayNN` packages,
pure part functions, typed ZIO file loading, ZIO tests, and the local Scalafix
guardrails. Publish the assigned day files, any necessary shared `aocYYYY.util`
files, its test input resources, and Main.scala explicitly. Do not restore the
old monolithic DayNN.scala layout or munit tests.
