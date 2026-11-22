---
name: AoC Solver - Scala
description: Solve every Advent of Code part from 2015 through 2025 in Scala 3, one day per CTO selection.
slug: aoc-solver-scala
schema: agentcompanies/v1
version: 2.0.0
license: MIT
authors:
  - name: Roland Tritsch
goals:
  - Complete all 524 parts across 262 days in 2015–2025, including authenticated finales
  - Publish tested, idiomatic, ScalaDoc-documented solutions to rolandtritsch/scala3-aoc
  - Check readiness once daily at 06:00 UTC and select the next unfinished day when clear
  - Use 0000 as the template and YYYY as each independent year project
---

The CTO authorizes one day at 06:00 UTC. Gatherer, Solver, and Submitter
execute its stages sequentially. Accepted part1 continues to part2; accepted
part2 ends the day. Rejections wait for the next daily or manual check.
There is no Reviewer, source audit, or algorithm assessment. Solver retains
the first-principles instruction. See [DESIGN.md][] for architecture and
[README.md][] for operations.

[DESIGN.md]: DESIGN.md
[README.md]: README.md
