"""Complete allowlisted company packages, independent of CLI file filtering."""
import json
from pathlib import Path

from common import Blocked, digest, git

AGENTS = ("cto", "problem-gatherer", "problem-solver", "problem-submitter")
SKILLS = ("aoc-runtime", "aoc-workflow", "aoc-gather", "aoc-solve-scala", "aoc-submit")


def collect(root):
    root = Path(root).resolve()
    names = ["COMPANY.md", ".paperclip.yaml", "tasks/daily-selection/TASK.md"]
    names += [f"agents/{agent}/AGENTS.md" for agent in AGENTS]
    names += [f"skills/{skill}/SKILL.md" for skill in SKILLS]
    names += [str(p.relative_to(root)) for p in sorted(
        (root / "skills/aoc-runtime/scripts").glob("*.py"))]
    names += [str(p.relative_to(root)) for p in sorted(
        (root / "skills/aoc-runtime/assets").rglob("*")) if p.is_file()]
    files = {}
    for name in names:
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise Blocked("Release resources must be real files inside the repository")
        files[name] = path.read_text()
    return files


def build(root):
    root = Path(root)
    files = collect(root)
    revision = git(root, "rev-parse", "HEAD")
    dirty = bool(git(root, "status", "--porcelain", "-uall"))
    checksum = digest(files)
    prefix = "skills/aoc-runtime/"
    manifest = {"schema": 1, "name": "aoc-runtime", "launcher": 1,
        "packageHash": checksum, "sourceCommit": revision, "dirty": dirty,
        "files": {k[len(prefix):]: digest(v.encode()) for k, v in files.items() if k.startswith(prefix)}}
    files[prefix + "release.json"] = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    return {"schema": 1, "packageHash": checksum, "sourceCommit": revision,
            "dirty": dirty, "files": files, "qualification": {}}


def payload(package, company=None, name=None):
    target = {"mode": "existing_company", "companyId": company} if company else {
        "mode": "new_company", "newCompanyName": name}
    if not company and not name:
        raise Blocked("New imports require a unique explicit company name")
    return {"source": {"type": "inline", "rootPath": ".", "files": package["files"]},
        "target": target, "include": {"company": True, "agents": True, "skills": True, "issues": True},
        "agents": "all", "collisionStrategy": "replace"}


def validate(package):
    files = dict(package["files"])
    manifest = json.loads(files.pop("skills/aoc-runtime/release.json"))
    if digest(files) != package["packageHash"] or manifest["packageHash"] != package["packageHash"]:
        raise Blocked("Saved release package was modified")
    if set(manifest["files"]) != {p[len("skills/aoc-runtime/"):] for p in files
                                  if p.startswith("skills/aoc-runtime/")}:
        raise Blocked("Incomplete runtime file inventory")
    for name, expected in manifest["files"].items():
        if digest(files["skills/aoc-runtime/" + name].encode()) != expected:
            raise Blocked("Runtime file hash mismatch")
