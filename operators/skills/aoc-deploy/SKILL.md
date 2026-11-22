---
name: aoc-deploy
description: Deploy or roll back AoC company instructions and executable helpers through the import API
---

Canonical source is `pcc-aoc-solver-scala/operators/skills/aoc-deploy`.
Resolve an installed symlink before locating the shared operator command:
`python3 <repository>/operators/aoc.py --help`.

Read [operations][] Company release. Use package then deploy plan/apply/verify with a saved record. Verify helper inventory, four roles, bindings, and the actual runtime release before activation. Routine code changes do not rebuild tools. Do not use the CLI file collector that drops Python resources.

Keep secrets out of arguments and output. Distinguish local checks from live
qualification. Use the existing authenticated local Paperclip login and AWS
profile `roland`. No company agent receives deployment authority.

[operations]: ../../OPERATIONS.md
