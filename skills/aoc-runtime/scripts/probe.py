"""Read-only runtime qualification, with no puzzle authorization or submission."""
import os
from pathlib import Path

from aoc_site import Page, Site, status
from common import Blocked, command, digest, git
from repository import ORIGIN


def qualify(api, task, company, agent, root, template=False):
    session = os.environ["AOC_SESSION"]
    site = Site(session, "")
    html = site.fetch(2015, 1)
    page = Page(html)
    if not page.user:
        raise Blocked("Authenticated AoC identity unavailable")
    account = digest(page.user)
    status(html, account, 1)
    permission = command(root, ["gh", "api", "repos/rolandtritsch/scala3-aoc", "--jq", ".permissions.push"])
    if permission != "true":
        raise Blocked("GitHub token does not have repository push permission")
    result = {"account": account, "releaseDelivery": os.environ["AOC_RELEASE"],
              "gitAuthorization": "push permission confirmed", "templateTests": "not requested"}
    if template:
        checkout = Path(root) / "qualification" / task
        checkout.parent.mkdir(parents=True, exist_ok=True)
        if not checkout.exists():
            command(root, ["git", "clone", "--depth", "1", ORIGIN, str(checkout)])
        if git(checkout, "status", "--porcelain"):
            raise Blocked("Qualification checkout is dirty")
        output = command(checkout / "0000", ["sbt", "--server", "--batch",
            "clean; compile; testOnly *; scalafmtCheckAll; scalafmtSbtCheck; run"])
        import re
        if not re.search(r"Passed: Total [1-9]\d*, Failed 0, Errors 0", output) or "Day00 - part1:" not in output:
            raise Blocked("Actual runtime template did not execute passing tests and runner")
        result["templateTests"] = {"commit": git(checkout, "rev-parse", "HEAD"),
            "summary": re.findall(r"Passed: Total [^\n]+", output), "outputHash": digest(output.encode())}
    api.put_document(task, "qualification", result)
    api.finish(task, agent, company)
    return result
