---
name: deploy-aoc-runtime-image
description: >
  Build, publish, and roll out the pcc-aoc-solver-scala runtime Docker image
  (the Fargate container agents SSH into), and rotate its SSH keypair if
  needed. Use when the user asks to rebuild/redeploy the AoC runtime image,
  push a fix to runtime/launch.py or the Dockerfile, or rotate the runtime's
  SSH key. Distinct from deploy-aoc-company: that skill deploys the Paperclip
  *company* (agents/skills/routine); this one deploys the *container image*
  those agents SSH into to actually execute.
---

# Deploy the AoC runtime image

The container image (`runtime/Dockerfile`, `runtime/launch.py`,
`runtime/agent.sh`, etc.) is a separate deployable from the Paperclip company
package — changing `runtime/launch.py` requires a new image build + ECS
rollout, not a company reimport.

## Build and publish

```bash
python3 runtime/publish.py --repository 519722017377.dkr.ecr.eu-west-1.amazonaws.com/paperclip-aoc-runtime \
  --profile roland --region eu-west-1 --build-label "fix=<short description>"
```

Requires `docker` and valid AWS credentials (`aws sso login --profile
roland` first if the session needs auth — ask the user to run that
themselves with the `!` prefix if it fails with "Unable to locate
credentials"). Prints the immutable digest reference
(`...@sha256:...`) — copy it for the next step.

## Roll it out

```bash
AWS_PROFILE=roland python3 operators/aoc.py tools plan --image <DIGEST_REF> --record /tmp/tools-record.json
AWS_PROFILE=roland python3 operators/aoc.py tools apply --image <DIGEST_REF> --record /tmp/tools-record.json
```

`apply` sets the Pulumi config, runs `preview`+`up`, and waits for the ECS
service to stabilize — `{"rollout": "COMPLETED", ...}` on success.

**Critical gotcha, hit for real on 2026-11-25**: a plain `pulumi preview` on
this stack can show *unrelated* pending changes alongside the real one
(e.g. an `aws:rds/instance:Instance` `instanceClass` drift from a stale
config value someone set earlier and never applied/reverted). **Always read
the preview's full resource list before applying.** If anything outside
`aoc-runtime-task-definition` / `aoc-runtime-service` shows up, scope the
apply explicitly rather than taking the unrelated change along for the
ride:

```bash
AWS_PROFILE=roland pulumi preview --non-interactive --diff   # read it, every resource
AWS_PROFILE=roland pulumi up --yes --non-interactive \
  --target 'urn:pulumi:paperclip::paperclip::aws:ecs/taskDefinition:TaskDefinition::aoc-runtime-task-definition' \
  --target 'urn:pulumi:paperclip::paperclip::aws:ecs/service:Service::aoc-runtime-service' \
  --target-dependents
```

`cwd` for all `pulumi`/`aws` commands here is `pulumi-paperclip/` (sibling
repo), not `pcc-aoc-solver-scala/`.

## Rotating the runtime's SSH keypair

The container only ever receives the **public** half, via Pulumi config
(`aoc_runtime_ssh_public_key`, injected as the `AOC_SSH_PUBLIC_KEY` env var
on the container, which writes it to `authorized_keys`). The private half
lives *only* in Paperclip's encrypted secret store — there is no file copy
anywhere, by the project's own stated design
(`pulumi-paperclip/README.md`: "client SSH private key belongs in
Paperclip-encrypted storage, not Pulumi config"). **If it's lost (e.g. the
owning company was archived), it cannot be recovered — generate a new one.**

```bash
ssh-keygen -t ed25519 -f /tmp/aoc_runtime_key -N "" -C "paperclip-aoc-runtime-$(date +%Y%m%d)"
cd ../pulumi-paperclip
AWS_PROFILE=roland pulumi config set aoc_runtime_ssh_public_key "$(cat /tmp/aoc_runtime_key.pub)"
AWS_PROFILE=roland pulumi preview --non-interactive   # expect exactly: aoc-runtime task def replace + service update
AWS_PROFILE=roland pulumi up --yes --non-interactive \
  --target 'urn:pulumi:paperclip::paperclip::aws:ecs/taskDefinition:TaskDefinition::aoc-runtime-task-definition' \
  --target 'urn:pulumi:paperclip::paperclip::aws:ecs/service:Service::aoc-runtime-service' \
  --target-dependents
AWS_PROFILE=roland aws ecs wait services-stable --cluster paperclip --services paperclip-aoc-runtime --region eu-west-1
```

Then bind the new private key to the Paperclip environment (see
`deploy-aoc-company` skill's environment section — either the long-lived
environment object or a fresh one is fine; a fresh environment was
previously suspected as the cause of an agent-verification failure, but
that was root-caused to an unrelated `cwd` config bug, now fixed — see
that skill's troubleshooting section) and immediately delete the local
private key file (`shred -u` or `rm -f`) — it should exist nowhere but
Paperclip's vault once bound.

```bash
python3 operators/aoc.py environment apply --company <COMPANY_ID> \
  --host runtime.aoc.paperclip.internal \
  --private-key-file /tmp/aoc_runtime_key --known-hosts-file <path with the unchanged host key>
shred -u /tmp/aoc_runtime_key
```

The server's host key (in `knownHosts`) does **not** change on a client-key
rotation — reuse the existing value from
`paperclipai environment get <env-id> --json`.

## Debugging inside the running container

**For an agent stuck in `lifecycleState: verifying`, try the
`deploy-aoc-company` skill's `test-environment` API call first** — it's
faster and gives a real stack trace directly, no container access needed.
Reach for ECS Exec below when you need to verify an image/file change
landed, or reproduce something the API call doesn't cover.

ECS Exec is enabled on this service. Useful for verifying a fix landed or
reproducing a failure directly, bypassing Paperclip's own SSH path entirely:

```bash
TASK_ARN=$(AWS_PROFILE=roland aws ecs list-tasks --cluster paperclip --service-name paperclip-aoc-runtime --region eu-west-1 --query 'taskArns[0]' --output text)
AWS_PROFILE=roland aws ecs execute-command --cluster paperclip --region eu-west-1 \
  --task "$TASK_ARN" --container aoc-runtime --interactive --command "/bin/sh"
```

You land as `root`; `su - paperclip` to act as the SSH user Paperclip
actually connects as. `/workspaces/agents` is the EFS-backed
`remoteWorkspacePath` — real, persistent, shared across container restarts.

Server-side logs: CloudWatch log group `/ecs/paperclip` (the Paperclip
application itself — structured JSON, one line per request/event; agent
lifecycle failures appear as `{"phase":"verifying","stage":"host",
"failureCode":...}` but **never include the underlying provider error text,
by design**) and `/ecs/paperclip-aoc-runtime` (this container's own stdout,
including sshd's own accept/disconnect lines — useful for confirming SSH
auth itself isn't the problem, since sshd logs connection accept/reject but
not the executed command's own output).
