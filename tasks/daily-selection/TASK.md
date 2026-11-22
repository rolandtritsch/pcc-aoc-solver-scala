---
name: Daily next-day selection
slug: daily-selection
assignee: cto
recurring: true
---

At 06:00 UTC, run the deterministic controller. Resume the current authorized
day or authorize at most one unfinished day, both parts sequentially. Never
select another day from a specialist notification. Complete this occurrence
after the decision. The separate control task tracks the authorized day.
