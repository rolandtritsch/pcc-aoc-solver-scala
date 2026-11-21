---
name: AoC Solver - Scala
description: Solve every Advent of Code part from 2015 through 2025 in Scala 3, one day per CTO selection.
slug: aoc-solver-scala
schema: agentcompanies/v1
version: 1.0.0
license: MIT
authors:
  - name: Roland Tritsch
goals:
  - Complete all 524 parts across 262 days in 2015–2025, including authenticated finales
  - Publish tested, idiomatic, ScalaDoc-documented solutions to rolandtritsch/scala3-aoc
  - Check readiness every two minutes and select the next unfinished day when clear
  - Use 0000 as the template and YYYY as each independent year project
---

The CTO checks readiness every two minutes and selects the earliest unfinished year/day when clear.
Order is 2015 Day01 through Day25, then 2016, through 2024 Day25,
then 2025 Day01 through Day12. Both parts belong to the authorized day;
part2 starts only after part1 acceptance and completed review. Rejections
are reviewed before the CTO can authorize a repair at a later readiness check.
An unfinished day blocks selection of another day. Final-day part2 follows
the authenticated completion interaction rather than an invented answer.

Solutions go to [scala3-aoc][repo], in `YYYY/`, using `0000/` as the reusable
template. Shared skills and improvements live at that repository's root.
The [daily task][daily] and `.paperclip.yaml` define the two-minute routine
assigned to the CTO; it is the only trigger for readiness checks, so the
CTO's own interval heartbeat stays disabled. This package does not modify the
original company. Agent/run health is monitored by Paperclip's native
watchdog mechanisms rather than a company-owned observer agent.

[repo]: https://github.com/rolandtritsch/scala3-aoc
[daily]: tasks/daily-selection/TASK.md
