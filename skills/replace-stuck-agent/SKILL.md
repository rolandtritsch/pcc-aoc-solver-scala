---
name: replace-stuck-agent
description: >
  Replace an aoc-solver-scala agent that's stuck forever in
  lifecycleState "pausing"/"terminating" (upstream paperclipai/paperclip
  #16346 and friends -- unfixed as of 2026-11-26) or otherwise needs to be
  recreated, without losing its generation/environment/account binding or
  orphaning tasks it still owns. Use when an agent won't resume, pause, or
  terminate cleanly, or when `deploy-aoc-company`'s stuck-pausing
  troubleshooting section says to orphan-and-recreate.
---

# Replace a stuck agent

**Use the script. Do not do this by hand** -- two real incidents
(2026-11-25 Solver, 2026-11-26 CTO) each needed a manual follow-up fix the
first time because a step was missed:

```bash
python3 operators/replace_agent.py --company <COMPANY_ID> --role cto
# roles: cto, problem-gatherer, problem-solver, problem-submitter
```

This does all of the following, in order, reusing the exact same
`operators/aoc.py` commands you'd otherwise run manually:

1. Reads the target role's **current** agent configuration and resolves
   `generation`/`environment`/`account` from it, before touching anything.
2. Records every open task still assigned to that agent.
3. Terminates it (`POST /agents/:id/terminate` -- status flips to
   `"terminated"` immediately; a lingering `"terminating"` lifecycleState
   in the background does not block anything downstream, so don't wait
   for it).
4. Redeploys (`aoc.py deploy plan` + `apply`), which creates the fresh
   replacement agent by name.
5. Rebinds it with the **preserved** generation/environment/account
   (`aoc.py bind apply`) -- never the auto-detected one.
6. Mints its standing Paperclip API key (`aoc.py credentials apply`).
7. Reassigns every task from step 2 to the replacement's agent id.
8. Verifies (`aoc.py bind verify`).

Prints the old/new agent ids, the resolved binding, and the reassigned
task list as JSON on success.

**After it finishes, you still need to**: resume all four agents and
re-enable the routine/trigger yourself (the redeploy's own `quiesce()`
paused everything again, exactly like every other `deploy apply`). The
script does not do this, since whether to re-enable is an operator call,
not automatic:

```python
import sys; sys.path.insert(0, "skills/aoc-runtime/scripts"); sys.path.insert(0, "operators")
from api import Api
from lifecycle import resume_ready
api = Api.local()
for agent_id in (CTO_ID, GATHERER_ID, SOLVER_ID, SUBMITTER_ID):
    resume_ready(api, agent_id)
# then PATCH the routine to status="active" and its trigger to enabled=True
```

## Why both of these steps are load-bearing (not optional hardening)

**Preserving generation/environment/account**: `operators/aoc.py deploy`'s
auto-detect generation logic reads the agent `imports()` sees via
`GET /companies/:id/agents` -- which **excludes terminated agents by
default** (confirmed by reading Paperclip's own
`company-portability.ts`: `agents.list()` only includes them with
`includeTerminated: true`, which this call doesn't pass). Once the target
role's old agent is terminated, there is nothing left to auto-detect from.
A careless `deploy apply` right after a termination silently:
- generates a **fresh random generation** (`str(uuid.uuid4())`) instead of
  reusing the real one, and
- skips the bind step entirely for **all four agents**, not just the
  replaced one (no `AOC_GENERATION`/`AOC_RELEASE`/`AOC_ACCOUNT`/etc. bound
  on any of them).

Either one breaks every future run: `repository.assert_owner()` checks the
live agent's `AOC_GENERATION` against `.aoc/owner.json`'s stored value and
raises `Blocked` on mismatch, and a missing `AOC_RELEASE`/`AOC_ACCOUNT`
fails `company.verify()`'s binding checks outright.

**Reassigning stale tasks**: a control task (or any open task) keeps
whatever `assigneeAgentId` it had when created. The replacement agent can
still *advance* it fine (creating children, reading/writing documents --
none of that checks ownership), but the final `self.api.finish(task, ...)`
call (`skills/aoc-runtime/scripts/api.py`'s own `finish()`, not a
Paperclip server check) asserts `row["assigneeAgentId"] == agent` and
raises `Blocked("Task ownership mismatch")` forever otherwise -- the task
just sits `in_progress`/`blocked` permanently, with the new agent
otherwise looking perfectly healthy (`idle`/`ready`, no error).

## If you ever see this fail partway through

The script is not itself transactional -- if a later step fails (e.g. the
redeploy's own `quiesce()` times out waiting for a still-"running" agent,
see `deploy-aoc-company`), the old agent is already terminated and you'll
need to finish the remaining steps by hand using the resolved
generation/environment/account it already printed (or re-derive them: the
account fingerprint is `digest(Page(html).user)` for any authenticated
page fetch; the environment id and generation are stable for the life of
the company -- check a surviving, undisturbed agent's own configuration).
