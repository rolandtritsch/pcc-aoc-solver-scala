---
name: aoc-replace-company
description: Replace and archive an AoC company while preserving published solutions and preventing competing runs
---

Canonical source is `pcc-aoc-solver-scala/operators/skills/aoc-replace-company`.
Resolve an installed symlink before locating the shared operator command:
`python3 <repository>/operators/aoc.py --help`.

Read [operations][] Replacement and activation. Plan against explicit old/new identities. Disable schedules as well as pausing agents; confirm zero live runs. Import the replacement paused, bind new company-local credentials, qualify, transfer repository ownership, and archive the old company. Never hard-delete or share company-scoped secret references.

Keep secrets out of arguments and output. Distinguish local checks from live
qualification. Use the existing authenticated local Paperclip login and AWS
profile `roland`. No company agent receives deployment authority.

[operations]: ../../OPERATIONS.md
