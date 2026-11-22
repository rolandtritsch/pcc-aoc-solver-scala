"""Retire old workflow assignments before activating the replacement engine."""
from common import Blocked
from company import assert_quiet


def retire_legacy(api, company):
    state = assert_quiet(api, company)
    rows = api.request("GET", f"/companies/{company}/issues?status=backlog,todo,in_progress,blocked,in_review&limit=1000")
    cancelled = []
    from workflow import assignment
    for row in rows:
        full = api.request("GET", "/issues/" + row["id"])
        if assignment(full):
            continue
        api.request("PATCH", "/issues/" + row["id"], {"status": "cancelled"})
        cancelled.append(row["id"])
    for agent in state["agents"]:
        if agent["name"] == "Solution Reviewer" and agent["status"] != "terminated":
            api.request("POST", f"/agents/{agent['id']}/terminate", {})
            saved = api.request("GET", "/agents/" + agent["id"])
            if saved["status"] != "terminated":
                raise Blocked("Reviewer termination pending; do not activate until resolved")
    removed = []
    for skill in api.request("GET", f"/companies/{company}/skills"):
        if skill["slug"] == "aoc-review":
            api.request("DELETE", f"/companies/{company}/skills/{skill['id']}")
            removed.append(skill["id"])
    return {"company": company, "cancelledLegacyTasks": cancelled, "removedReviewSkills": removed}
