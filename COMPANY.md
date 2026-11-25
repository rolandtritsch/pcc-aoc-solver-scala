---
name: AoC Solver - Scala
description: Solve every Advent of Code part from 2015 through 2025 in Scala 3, one day per CTO selection.
slug: aoc-solver-scala
schema: agentcompanies/v1
version: 3.0.0
license: MIT
authors:
  - name: Roland Tritsch
goals:
  - Complete all 524 parts across 262 days in 2015–2025, including authenticated finales
  - Publish tested solutions to rolandtritsch/scala3-aoc, conventions owned by that repo's AGENTS.md
  - Reconcile against repo + site every tick at 06:00 UTC; never trust a stored cursor
  - Use 0000 as the template and YYYY as each independent year project
---

The CTO owns a lease-fenced reconciliation loop, not a stored progress cursor.
Gatherer, Solver, and Submitter execute its assigned stages sequentially.
Accepted part1 continues to part2; accepted part2 ends the day. Rejections
wait for the next reconcile tick or manual check. There is no Reviewer,
source audit, or algorithm assessment. Solver retains the first-principles
instruction. Authority model and state machine: see
[docs/2026-11-25_refactor-analysis.md][refactor-analysis]. Architecture:
see [DESIGN.md][]. Operations: see [README.md][].

[refactor-analysis]: docs/2026-11-25_refactor-analysis.md
[DESIGN.md]: DESIGN.md
[README.md]: README.md
