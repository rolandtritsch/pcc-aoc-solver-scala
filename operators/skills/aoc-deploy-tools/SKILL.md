---
name: aoc-deploy-tools
description: Build, deploy, verify, or roll back the dedicated AoC Fargate tools image
---

Canonical source is `pcc-aoc-solver-scala/operators/skills/aoc-deploy-tools`.
Resolve an installed symlink before locating the shared operator command:
`python3 <repository>/operators/aoc.py --help`.

Read [operations][] Tools and bootstrap. Change the tools image only for toolchain/bootstrap changes. Publish an immutable digest, plan/apply the infrastructure change, and verify completed rollout plus the actual task digest and template execution. Record the previous digest for rollback. Preserve the credential broker and SSH host pinning.

Keep secrets out of arguments and output. Distinguish local checks from live
qualification. Use the existing authenticated local Paperclip login and AWS
profile `roland`. No company agent receives deployment authority.

[operations]: ../../OPERATIONS.md
