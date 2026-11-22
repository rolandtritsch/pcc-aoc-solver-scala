# Operator procedures

Run `python3 operators/aoc.py --help` from the company repository. Canonical
skills live under `operators/skills/`; install them with
`python3 operators/aoc.py install`. All mutating workflows start with a saved
plan record. Records and saved packages are mode 0600. They contain no secrets.

## Company release

```bash
python3 operators/aoc.py package --package .paperclip/releases/aoc-package.json
python3 operators/aoc.py deploy plan --company COMPANY --package .paperclip/releases/aoc-package.json --record .paperclip/operations/aoc-deploy.json
python3 operators/aoc.py deploy apply --record .paperclip/operations/aoc-deploy.json
python3 operators/aoc.py deploy verify --record .paperclip/operations/aoc-deploy.json
```

For a fresh company use `--name UNIQUE_NAME` instead of `--company`. The
wrapper sends Python resources directly to the board import API. Do not use
the CLI's Markdown-only package collector or the company-scoped safe import
route for a replace operation. Inspect preview role/config/trigger inventories.
Unknown import responses stop for live readback; never repeat a new-company
import blindly. A saved package is also the rollback artifact: deploy it using
the same sequence. Do not reconstruct rollback from an unpinned branch name.

Imported companies remain paused with disabled routines. Bind the environment,
generation, account fingerprint, and release:

```bash
python3 operators/aoc.py bind apply --company COMPANY --environment ENVIRONMENT --generation GENERATION --account ACCOUNT_HASH --package .paperclip/releases/aoc-package.json
```

Supply integration values only via a mode-0600 `--secrets-file` or existing
vault bindings; never put values in arguments, comments, or journals. Create
each role's standing agent-scoped API key and bind it under
`AOC_PAPERCLIP_API_KEY`; do not share the CTO key. This avoids the observed
SSH/legacy run-token 401 without granting infrastructure access. Verify each
key against that role's own identity before activation.

## Replacement and activation

`replace plan --company OLD --name UNIQUE_NEW --record RECORD` previews a
replacement. `replace apply --record RECORD` disables old schedules, pauses
agents, confirms drain, and imports a paused new company. It deliberately
does not transfer ownership or archive until new-company qualification passes.

Before cutover, use `retire apply --company COMPANY` to cancel legacy open
assignments and terminate the removed Reviewer after the company is quiesced.
This preserves historical issues and prevents resume from continuing old work.
`credentials apply --company COMPANY` creates separate standing keys and stores
them in the company vault. Imports declare values optional for staged creation;
`deploy verify` and activation require actual bindings.

Use `probe apply --company COMPANY --generation UNIQUE_PROBE_ID` for a dedicated
read-only qualification task. It checks imported code, account identity, GitHub
push permission, and real template tests; it never authorizes a puzzle. Wait for
its `qualification` document and pause CTO again before further maintenance.
`reconcile apply` similarly verifies historical accepted parts, publishes progress,
and stops at the first unsolved part without authorizing it.

Before cutover, verify the actual tools image supports launcher v1, pin SSH
host identity from authenticated ECS Exec, probe the environment, inspect
imported helper hashes on a real run, and execute the actual template suite.
Check Git push authorization separately from public cloning. Confirm one
routine, four roles, all bindings, and zero live runs. Use `own apply` only
with the new company paused and the old company drained. Then use `archive apply --company OLD` to retire the old company and revoke
its agent keys. Use `activate apply --company COMPANY --qualification FILE`
with actual qualification evidence to resume roles and enable the single trigger.
Reread agent status, live runs, and trigger nextRunAt. A first manual
check is explicit day authorization and may submit real answers.

## Tools and bootstrap

Publish the tools image with `runtime/publish.py --repository ECR_URL`.
Record its immutable digest. Plan/apply with:

```bash
python3 operators/aoc.py tools plan --image ECR_URL@sha256:DIGEST --record .paperclip/operations/aoc-tools.json
python3 operators/aoc.py tools apply --record .paperclip/operations/aoc-tools.json
python3 operators/aoc.py tools verify --record .paperclip/operations/aoc-tools.json
```

The image has no company workflow code. A helper-only update needs import,
not an image rebuild. Roll back by planning the previous recorded digest.
After `pulumi up`, wait for completed ECS rollout and inspect actual running
image digests; an old healthy task is not proof of the new release.

For a fresh stack, supply the Pulumi backend login and AWS profile `roland`,
select an explicit stack, and start from `Pulumi.paperclip.yaml.example`.
Provision the runtime repository first, publish tools, then set its digest.
`bootstrap plan/apply` previews and applies the configured stack. Bootstrap
the Paperclip board login using its documented CLI workflow, create the SSH
environment with a company-local private-key secret, import the company,
bind credentials, and qualify it before enabling the schedule. Account/secret
provisioning is not implied by successful infrastructure creation.

## Recovery boundaries

Diagnose first. A workspace issue is not an authentication issue, and an image
redeploy does not clear EFS. Prefer quarantine to deletion. Runtime cache
quarantine is executed through authenticated ECS Exec on the runtime, under `/workspaces/aoc/checkouts`,
while the company is quiesced. Preserve unexpected local work for inspection.

`recover plan --scope SCOPE --company COMPANY --record RECORD` records exact
stack outputs, affected companies, and the requested storage boundary.
Scopes are workspace, progress, runtime-efs, controller-efs, database, and instance.
Read and explain the concrete plan before asking approval. Pass its plan hash
as `--approval` only after the user explicitly approves that operation.
Never invent approval from a generic request to repair the company.

Controller/database resets need a verified paired database/master-key backup
reference (`--backup`). Check it exists and is restorable before applying.
The operation journal is not a backup. EFS/database replacement is performed
through explicit Pulumi generation settings, with data protection restored
afterward. Inspect the preview for unrelated replacements before applying.

Runtime EFS reset loses SSH host identity: read and repin the new host key
through authenticated ECS Exec before reconnecting. A database-only reset
loses companies and vault entries even if EFS survives. Controller-EFS-only
reset loses the vault key: restore the matching key before allowing the
existing database to serve runs. Whole-instance fresh reset requires board
bootstrap, new credentials, imports, ownership binding, and reconciliation.

Full reset and fresh-stack acceptance must first run on a disposable stack.
Report absent evidence as unqualified; never use production to demonstrate
destructive behavior without an explicit approved test plan.
