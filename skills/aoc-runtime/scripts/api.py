"""Authenticated API access, bounded reads and optimistic task documents."""
import json
import os
from pathlib import Path
import time
import tempfile
import urllib.error
import urllib.request

from common import Blocked


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Api:
    def __init__(self, base, token, run_id=None):
        if not base.startswith("https://") and not base.startswith("http://localhost:"):
            raise Blocked("API requires HTTPS or localhost")
        self.base, self.token, self.run_id = base.rstrip("/"), token, run_id
        self.opener = urllib.request.build_opener(NoRedirect)

    @classmethod
    def local(cls):
        home = Path.home() / ".paperclip"
        context = json.loads((home / "context.json").read_text())
        profile = context["profiles"][context["currentProfile"]]
        base = os.environ.get("PAPERCLIP_API_URL", profile["apiBase"]).rstrip("/")
        auth = json.loads((home / "auth.json").read_text())
        return cls(base, os.environ.get("PAPERCLIP_API_KEY") or
                   auth["credentials"][base]["token"])

    @classmethod
    def runtime(cls):
        return cls(os.environ.get("AOC_PAPERCLIP_API_URL") or os.environ["PAPERCLIP_API_URL"],
                   os.environ["AOC_PAPERCLIP_API_KEY"], os.environ["PAPERCLIP_RUN_ID"])

    def request(self, method, path, body=None):
        headers = {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"}
        if self.run_id:
            headers["X-Paperclip-Run-Id"] = self.run_id
        for attempt in range(3 if method == "GET" else 1):
            request = urllib.request.Request(self.base + "/api" + path, method=method,
                headers=headers, data=None if body is None else json.dumps(body).encode())
            try:
                with self.opener.open(request, timeout=30) as response:
                    raw = response.read(16 * 1024 * 1024)
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as error:
                if method == "GET" and error.code in (429, 502, 503, 504) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                if method == "GET" and error.code == 404:
                    raise Blocked(f"Paperclip {method} {path}: HTTP 404") from None
                with tempfile.NamedTemporaryFile(mode="wb", prefix="aoc-api-", suffix=".json", delete=False) as out:
                    out.write(error.read(1024 * 1024))
                    diagnostic = out.name
                raise Blocked(f"Paperclip {method} {path}: HTTP {error.code}; private diagnostic {diagnostic}") from None
            except (urllib.error.URLError, TimeoutError):
                if method == "GET" and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise Blocked(f"Paperclip {method} {path}: transport uncertainty; read back before retry") from None

    def document(self, task, key):
        try:
            row = self.request("GET", f"/issues/{task}/documents/{key}")
        except Blocked as error:
            if str(error).endswith("HTTP 404"):
                return None, None
            raise
        return json.loads(row["body"]), row.get("latestRevisionId") or row.get("revisionId")

    def put_document(self, task, key, value):
        previous, revision = self.document(task, key)
        if previous == value:
            return
        self.request("PUT", f"/issues/{task}/documents/{key}", {
            "title": key, "format": "markdown", "body": json.dumps(value, sort_keys=True),
            "baseRevisionId": revision})
        saved, _ = self.document(task, key)
        if saved != value:
            raise Blocked("Task document write did not persist")

    def finish(self, task, agent, company, status="done"):
        row = self.request("GET", "/issues/" + task)
        if row["companyId"] != company or row.get("assigneeAgentId") != agent:
            raise Blocked("Task ownership mismatch")
        if row["status"] == status:
            return
        saved = self.request("PATCH", "/issues/" + task, {"status": status})
        if saved.get("status") != status:
            raise Blocked("Task disposition not persisted")
