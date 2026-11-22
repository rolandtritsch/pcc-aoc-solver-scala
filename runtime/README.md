# Dedicated tools runtime

Fargate runs an SSH service with pinned Java, sbt, OpenCode, Git, GitHub CLI,
and Python. Tool pins are in `toolchain.json`. The image contains no company
workflow implementation. `launch.py` verifies the run-specific imported
`aoc-runtime` manifest before executing its Python entry point.

Publish with `python3 runtime/publish.py --repository ECR_URL`. Deploy its
immutable digest through the unified [operator procedures][operations]. A
company helper change requires an import, not another tools image.

Runtime EFS holds caches, isolated solution checkouts, submission checkpoints,
and SSH host identity. Controller EFS is separate. Replacing tasks preserves
EFS; resetting runtime EFS requires authenticated host-key repinning. Never
trust an unauthenticated host-key scan. Keep the run credential broker ahead
of ordinary Git binaries in PATH.

The OpenCode legacy adapter remains the transport. Its exact credential-free
hello probe only establishes launcher/provider availability. Qualification
also requires real imported helper hashes, authenticated Git authorization,
account identity, actual template tests, and completed ECS rollout.

[operations]: ../operators/OPERATIONS.md
