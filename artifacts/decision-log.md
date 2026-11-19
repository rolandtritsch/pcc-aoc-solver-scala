# Decision Log — AoC Solver - Scala

## 2026-11-19

- User authorized importing the multi-year Scala company and demonstrating 2015 Day01 part1 through the agent pipeline.
- Imported seven agents and the daily-selection routine into this new AOC company. The unrelated LEP company was preserved.
- Fixed portable schedule list indentation; preview confirms cron `0 6 * * *`, timezone `Europe/Dublin`.
- Explicitly selected the legacy OpenCode runner: the current Paperclip Runner rejects custom launcher commands required by the CTO preflight gate and WatchDog.
- Linked infrastructure-owned AWS Secrets Manager references for OpenRouter, AoC session and GitHub authentication; no secret values copied into package files.
- Installed Java 25 and sbt 2.0.10 under persistent /paperclip storage; canonical solution checkout is /paperclip/workspaces/scala3-aoc.
- Set a fresh cycle start. Keep the routine paused until runtime checks pass; WatchDog and Model Tester remain paused. Initial objective is 2015 Day01 part1 with a tested, pushed solution and authoritative submission/acceptance evidence.
