---
name: aoc-diagnose
description: Diagnose AoC company workflow, imported release, credentials, runtime, and infrastructure without changing state
---

Canonical source is `pcc-aoc-solver-scala/operators/skills/aoc-diagnose`.
Resolve an installed symlink before locating the shared operator command:
`python3 <repository>/operators/aoc.py --help`.

Run `diagnose` first, identify the actual failing boundary, then inspect the smallest relevant layer. Read [operations][]. Do not recommend reimport for a verified credential failure or a rebuild for stale EFS. Compare source, imported helpers, image, and live configuration separately.

Keep secrets out of arguments and output. Distinguish local checks from live
qualification. Use the existing authenticated local Paperclip login and AWS
profile `roland`. No company agent receives deployment authority.

[operations]: ../../OPERATIONS.md
