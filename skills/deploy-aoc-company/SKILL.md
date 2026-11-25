---
name: deploy-aoc-company
description: >
  Deploy or redeploy the pcc-aoc-solver-scala Paperclip company for real,
  against the live Paperclip instance, using this repo's own operators/aoc.py
  pipeline (not the generic `paperclipai company import` CLI). Use when the
  user asks to deploy, redeploy, replace, or bring up the AoC Solver company,
  or when a deployed company is missing runtime code / stuck on agent
  lifecycle verification. Covers the full real sequence: package -> deploy ->
  credentials -> environment -> secrets -> bind -> own -> probe -> activate,
  with the gotchas actually hit doing this for real on 2026-11-25.
---

# Deploy the AoC Solver company

This is the real, validated sequence — not the generic Agent Companies
`paperclipai company import` CLI, which only imports `SKILL.md` markdown and
silently drops the actual Python runtime (`skills/aoc-runtime/scripts/*.py`).
Always use `operators/aoc.py`, which bundles the real `.py` files via
`operators/package.py`'s `collect()`/`build()`.

Run every command from the repo root (`pcc-aoc-solver-scala/`). Every
destructive/mutating action below is plan-then-apply: run `plan` first, read
the output, then `apply` with the same `--record` path.

## 0. Redeploying to an already-live company: check for a running agent first

`deploy apply` on an existing company always calls `quiesce()` first, which
pauses every agent. `operators/company.py`'s `quiesce()` now refuses to pause
an agent whose `status` is `"running"` — it waits for it to go idle on its
own (bounded by `timeout`, default 30 min) instead. **Do not work around this
by shortening the timeout or pausing agents manually first.** Pausing an
agent mid-run cancels that run, and on an SSH/remote environment the
cancelled run's lease never gets a termination receipt — Paperclip's own
stop-check can then never prove the remote process died, and the agent gets
stuck in `lifecycleState: pausing` **forever**, with no known API/CLI lever
to clear it (see AGENTS.md's "stuck in pausing" note; upstream
paperclipai/paperclip#16346, open PR #20766 not yet merged).

Before running `deploy apply` against a live company, check first:

```python
import sys; sys.path.insert(0, "skills/aoc-runtime/scripts")
from api import Api
api = Api.local()
for a in api.request("GET", f"/companies/{COMPANY_ID}/agents"):
    print(a["id"], a["name"], a["status"])
```

If the Solver shows `"running"`, it's mid-way through an sbt/model cycle
that can legitimately take 10-15+ minutes — just wait (or let `quiesce()`'s
own wait loop do it) rather than forcing a pause. If an agent is stuck in
`"pausing"` from a **previous** incident, `quiesce()`'s wait loop will not
help (it's not "running", it's already stuck) — see the Troubleshooting
section at the bottom before doing anything else with that agent.

## 1. New company, fresh deploy

```bash
python3 operators/aoc.py deploy plan --name "AoC Solver - Scala" --record /tmp/deploy-record.json
python3 operators/aoc.py deploy apply --record /tmp/deploy-record.json
```

Check the plan output has exactly 4 agents (cto, problem-gatherer,
problem-solver, problem-submitter), all `opencode_local`, and the single
`0 6 * * *` trigger — `imports()` itself asserts this and raises `Blocked` if
not. `apply` creates the company, imports agents+skills+routine, and leaves
everything **paused**.

**Verify the real files actually landed** (the one thing the generic import
silently skips):

```bash
paperclipai skill list --company-id <COMPANY_ID> --json   # find the aoc-runtime skill id
paperclipai skill get <SKILL_ID> --company-id <COMPANY_ID> --json | python3 -c "import json,sys; print(len(json.load(sys.stdin)['fileInventory']))"
```

Should be ~47 files including `scripts/workflow.py`, `scripts/aoc_state.py`,
`scripts/aoc_repair.py`. If it's `1` (just `SKILL.md`), you used the wrong
import path — archive this company (`archive apply --company ID`) and redo
with `operators/aoc.py deploy`, not `paperclipai company import`.

## 2. Credentials (self-contained, no secrets needed)

```bash
python3 operators/aoc.py credentials apply --company <COMPANY_ID>
```

Generates a standing Paperclip API key per agent and binds it as
`AOC_PAPERCLIP_API_KEY`. No external input required.

## 3. SSH environment

There is a long-lived environment object, `b27409b6-18d5-40bf-afe1-0ffb64643b13`
(name `"AoC Scala runtime"`), that has been manually rebound across company
generations rather than recreated each time via `environment()`'s own
company-scoped naming (`"AoC Scala " + company_id`). **Prefer rebinding to
that existing environment** over creating a fresh one — a brand-new
environment object is not known to behave identically for agent lifecycle
verification (see Troubleshooting below); this was not fully root-caused.

To create a *new* environment anyway (e.g. after a real key rotation — see
`deploy-aoc-runtime-image` skill):

```bash
python3 operators/aoc.py environment apply --company <COMPANY_ID> \
  --host runtime.aoc.paperclip.internal \
  --private-key-file <path, mode 600, delete after> \
  --known-hosts-file <path>
```

`host` is `runtime.aoc.paperclip.internal`; get the current `knownHosts`
value and `privateKeySecretRef` from `paperclipai environment get
b27409b6-18d5-40bf-afe1-0ffb64643b13 --json` if you need to confirm they
still match the live container. The SSH *public* key is only ever injected
into the container via Pulumi config (`aoc_runtime_ssh_public_key` in
`pulumi-paperclip`); the private half only ever lives in Paperclip's
encrypted secret store — there is no file copy to recover if lost. See the
`deploy-aoc-runtime-image` skill for rotating it.

## 4. Secrets file

Build `.paperclip/secrets/aoc-secrets.json` (already gitignored explicitly,
not just via the wholesale `.paperclip/` rule — check `.gitignore` has
`.paperclip/secrets/` before creating it in a new checkout):

```json
{
  "GH_TOKEN": "...",
  "AOC_SESSION": "...",
  "OPENROUTER_API_KEY": "..."
}
```

- `GH_TOKEN`: `gh auth token` (needs `repo` scope at minimum, pushes to
  `scala3-aoc`).
- `AOC_SESSION`: the user's adventofcode.com session cookie value — ask them
  to paste it (there's no way to fetch it programmatically) and tell them
  logging out/in afterward invalidates it if it was pasted into chat.
- `OPENROUTER_API_KEY`: ask the user.

`.paperclip.yaml` declares `OPENROUTER_API_KEY` as a secret input for
`problem-solver` only, and that's correct: `operators/company.py`'s
`verify()` only requires it on Solver, and `bind()`'s automatic
cross-agent secret sharing only redistributes `GH_TOKEN`/`AOC_SESSION`, not
`OPENROUTER_API_KEY`. (An earlier investigation this session briefly
suspected all four roles needed it, since the real `opencode_local` adapter
technically runs an `openrouter/*` model for every role — but CTO/
Gatherer/Submitter's hello-probe is stubbed in `runtime/launch.py` and
never actually calls OpenRouter, so this was a dead end. If you ever see it
suspected again, it's not the cause — see Troubleshooting.)

Bind secrets directly via the API (there's no `--secrets-file` path once a
company already exists without them — that flag only works on a fresh
`deploy`/`replace` import):

```python
import sys; sys.path.insert(0, "skills/aoc-runtime/scripts")
from api import Api
api = Api.local()
for key in ("GH_TOKEN", "AOC_SESSION", "OPENROUTER_API_KEY"):
    secret = api.request("POST", f"/companies/{COMPANY}/secrets",
        {"name": f"aoc-{key.lower()}", "provider": "local_encrypted", "value": VALUES[key]})
    # then PATCH each agent's adapterConfig.env[key] = {"type": "secret_ref", "secretId": secret["id"], "version": "latest"}
    # cto/gatherer/submitter: GH_TOKEN + AOC_SESSION
    # solver: GH_TOKEN + OPENROUTER_API_KEY (no AOC_SESSION — solver never touches the site)
```

Always read the agent's current `configurationRevision` and pass it back as
`expectedConfigurationRevision` in the `PATCH /agents/{id}` body (optimistic
concurrency).

## 5. Account fingerprint

`--account` for `bind` is `digest(page.user)` — a SHA-256 of the AoC display
name scraped from an authenticated page. Compute it with one real, read-only
GET (safe, no puzzle interaction):

```python
import sys; sys.path.insert(0, "skills/aoc-runtime/scripts")
from aoc_site import Site, Page
from common import digest
site = Site(AOC_SESSION_VALUE, account=None)
html = site.fetch(2015, 1)  # any solved day works
print(digest(Page(html).user))
```

(Calling `site.page(...)` instead raises `Blocked` because it checks account
match against `None` — use `fetch()` + `Page()` directly.)

## 6. Bind, own, verify

```bash
python3 operators/aoc.py package --package /tmp/release-package.json
python3 operators/aoc.py bind apply --company <COMPANY_ID> --environment <ENV_ID> \
  --generation <GENERATION_FROM_DEPLOY_OUTPUT> --account <FINGERPRINT> \
  --package /tmp/release-package.json
python3 operators/aoc.py own apply --repository /path/to/scala3-aoc \
  --company <COMPANY_ID> --generation <GENERATION>
python3 operators/aoc.py deploy verify --record /tmp/deploy-record.json
```

`own apply` commits `.aoc/owner.json` to `scala3-aoc` and pushes — it needs
a clean checkout with the right `origin` remote; no special prep otherwise.

## Troubleshooting: agent stuck in `lifecycleState: verifying`

`paperclipai agent get <ID> --json` shows `lifecycleError:
"Execution configuration check failed... It will retry automatically...
contact your instance administrator"` (the generic fallback text), retried
forever. Paperclip's lifecycle worker deliberately never logs or exposes
the underlying provider error for this (confirmed in
`paperclip/doc/AGENT-LIFECYCLE.md`: "The host stores a fixed error message.
It does not store the provider error text."), and CloudWatch
(`/ecs/paperclip`) only ever shows `{"phase":"verifying","stage":"host",
"failureCode":"unclassified"}` — no detail. **Don't try to debug it from
there.** Go straight to the one place that *does* return the full,
unredacted result:

```python
import sys, json; sys.path.insert(0, "skills/aoc-runtime/scripts")
from api import Api
api = Api.local()
config = api.request("GET", f"/agents/{AGENT_ID}/configuration")
result = api.request("POST", f"/companies/{COMPANY_ID}/adapters/opencode_local/test-environment",
    {"agentId": AGENT_ID, "adapterConfig": config["adapterConfig"]})
print(json.dumps(result, indent=2))
```

This calls the exact same `testEnvironment()` the lifecycle worker calls,
synchronously, and returns the full `checks` array with real messages/
stack traces on a 500 — not the stripped lifecycle error. **You must pass
`adapterConfig` explicitly** (fetched from the agent) — omitting it silently
tests schema defaults (`command: "opencode"`, generic `cwd`) instead of the
agent's real saved config, which will falsely report `"pass"`.

**Confirmed root cause, 2026-11-25**: the above call returned HTTP 500 with
a real stack trace: `mkdir: cannot create directory '/paperclip':
Permission denied`. `operators/company.py`'s `bind()` was setting
`adapterConfig.cwd` to the Paperclip *server's own local* instructions-
bundle path (`/paperclip/instances/default/companies/.../instructions`) —
correct for a locally-executed agent, but meaningless (and
unwritable-by-design) on a *remote* SSH-executed agent's own host. Every
"host" verification step tried to `mkdir -p` that path on the remote
container as the unprivileged `paperclip` user and failed with a raw,
uncategorized exception (no recognized Paperclip error `.code`), which is
exactly why it surfaced only as the generic "unclassified" fallback instead
of a specific, actionable message. **Fixed**: `bind()` now checks the
target environment's `driver`; for `"ssh"` it sets `cwd` to that
environment's own `remoteWorkspacePath` instead. See
`tests/test_operators.py::test_bind_uses_remote_workspace_as_cwd_on_an_ssh_environment`.
If you ever see this exact failure again on a *different* environment/
company, it's almost certainly the same class of bug recurring somewhere
new — check `cwd` against the bound environment's driver first, via the
`test-environment` call above, before chasing anything else.

Two real dead ends hit while narrowing this down, kept here so they aren't
re-walked: (1) a brittle exact-byte stdin comparison in `runtime/launch.py`
(fixed anyway, real bug, just not *this* bug — see
`deploy-aoc-runtime-image`'s notes); (2) suspecting `OPENROUTER_API_KEY`
was needed on all four roles (it isn't — see the secrets section above).

## Troubleshooting: agent stuck in `lifecycleState: pausing` forever

This is **upstream paperclipai/paperclip#16346** ("Pause never completes for
agents with a cancelled run on an SSH environment"), confirmed by many
independent reporters on the issue, plus duplicates #17803, #21154, #20801,
#22296, #18993, #17718, #20415, #16734. There is an open fix PR, **#20766**,
not yet merged (shows merge conflicts against master as of 2026-11-25) — no
ETA. Do not wait for it; this will keep happening until it lands.

**Mechanism**: pausing an agent cancels its in-flight run. For a non-local
(SSH) lease, Paperclip's `agentExecutionsHaveStopped`
(`server/src/services/agent-execution-stop.ts`) requires a "remote
termination receipt" proving the remote process died before it'll consider
the run stopped — but the SSH driver's `releaseRunLease` never writes one.
So any agent with even one cancelled SSH run in its *entire history* can
never finish pausing; `resume`, `lifecycle/retry`, and a server restart all
no-op.

**Prevention** (do this, not the repair): never pause a `"running"` agent.
`operators/company.py`'s `quiesce()` already enforces this — it waits for
`"running"` to clear before issuing pause, instead of cancelling the run.
If you're ever tempted to bypass that (shorten the timeout, pause via the
API directly, `paperclipai agent pause` by hand), don't — that's exactly
how this gets triggered.

**If it's already stuck** (pre-existing from before this safeguard, or
triggered some other way — e.g. a Board comment interrupting a run, an
issue reassignment, a budget hard-stop): confirmed NOT to help —
`paperclipai agent runtime-state:reset-session` (only clears client-side
session tracking), `heartbeat:invoke` (409s on a paused agent), re-issuing
`pause` (no-op). No CLI/API lever was found that forces it to clear.
Workaround used across every report on #16346: independently verify the
remote process is truly gone (`aws ecs execute-command ... ps aux` on the
SSH host — look for an orphaned process, not necessarily the exact
opencode/python one; our incident left a detached `sbt` server), then
either get direct DB access to the Paperclip instance to manually write the
termination receipt (needs an operator with that access; not available via
the CLI/API we use) or orphan the stuck agent (leave it
terminated-but-undeleted) and create a replacement. Don't burn time trying
to force it through the transition any other way.

## Key IDs from 2026-11-25 (may be stale — verify before reusing)

- Long-lived SSH environment: `b27409b6-18d5-40bf-afe1-0ffb64643b13`
  ("AoC Scala runtime", host `runtime.aoc.paperclip.internal`).
- Live company as of this writing: check `paperclipai company list --json`
  for the one with `status: active` and name `"AoC Solver - Scala"`.
