---
name: Daily next-day selection
slug: daily-selection
assignee: cto
recurring: true
---

Each hour, reconcile from 2015 day01 onward (repo + authenticated site are
truth; never trust a stored cursor) and act on the first part not yet
accepted. If a candidate solution is already committed for that part,
verify it end to end and dispatch straight to the Submitter to confirm it
against the real site. If verification fails or no candidate exists, run
the full gather -> solve -> submit pipeline. Resume the current authorized
day rather than selecting a new one from a specialist notification.
Complete this occurrence after the decision. The separate control task
tracks the authorized day.
