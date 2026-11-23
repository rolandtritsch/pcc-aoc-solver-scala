"""Private checkouts, explicit repository ownership, and commit-bound receipts."""
from pathlib import Path
import re
import shutil

from common import Blocked, command, digest, git, read_json, write_json

ORIGIN = "https://github.com/rolandtritsch/scala3-aoc.git"


class Repository:
    def __init__(self, path, owner, origin=ORIGIN):
        self.path, self.owner, self.origin = Path(path), owner, origin

    @classmethod
    def prepare(cls, root, name, owner, origin=ORIGIN, allowed_dirty=None):
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
            raise Blocked("Invalid workspace identity")
        root = Path(root).resolve()
        path = root / "checkouts" / name
        if path.is_symlink():
            raise Blocked("Workspace must not be a symlink")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            command(root, ["git", "clone", origin, str(path)])
        repo = cls(path, owner, origin)
        repo.sync(allowed_dirty)
        return repo

    def clean(self):
        if git(self.path, "status", "--porcelain", "-uall"):
            raise Blocked("Dirty checkout preserved; publish intended files or quarantine explicitly")

    def sync(self, allowed_dirty=None):
        if git(self.path, "remote", "get-url", "origin") != self.origin:
            raise Blocked("Unexpected solution origin")
        if git(self.path, "branch", "--show-current") != "main":
            raise Blocked("Solution checkout must use main")
        git(self.path, "config", "user.name", "AoC Solver")
        git(self.path, "config", "user.email", "aoc-solver@users.noreply.github.com")
        git(self.path, "config", "credential.https://github.com.helper", "!gh auth git-credential")
        dirty = {line[3:] for line in git(self.path, "status", "--porcelain", "-uall").splitlines()}
        if dirty and (allowed_dirty is None or not all(name in allowed_dirty for name in dirty)):
            raise Blocked("Unexpected dirty checkout preserved; quarantine or reconcile explicitly")
        git(self.path, "fetch", "origin", "main")
        if dirty:
            self.parity()  # Resume only this attempt's files on the exact live base.
            return git(self.path, "rev-parse", "HEAD")
        # AHEAD is also unexpected: do not publish arbitrary stranded commits.
        git(self.path, "merge-base", "--is-ancestor", "HEAD", "origin/main")
        git(self.path, "merge", "--ff-only", "origin/main")
        self.parity()
        return git(self.path, "rev-parse", "HEAD")

    def parity(self):
        head = git(self.path, "rev-parse", "HEAD")
        remote = git(self.path, "ls-remote", "origin", "refs/heads/main").split()[0]
        if head != remote:
            raise Blocked("Local and live remote main disagree")
        return head

    def assert_owner(self):
        git(self.path, "fetch", "origin", "main")
        raw = git(self.path, "show", "origin/main:.aoc/owner.json")
        import json
        if json.loads(raw) != self.owner:
            raise Blocked("Repository belongs to another company generation")

    def commit(self, files, message, force=False):
        self.assert_owner()
        dirty = {line[3:] for line in git(self.path, "status", "--porcelain", "-uall").splitlines()}
        if not dirty <= set(files):
            raise Blocked("Unrelated changes preserved; cannot publish")
        for name in files:
            target = self.path / name
            if target.is_symlink() or not target.resolve().is_relative_to(self.path.resolve()):
                raise Blocked("Publication path escapes checkout")
        git(self.path, "add", *( ["--force"] if force else []), "--", *files)
        if git(self.path, "diff", "--cached", "--name-only"):
            git(self.path, "diff", "--cached", "--check")
            git(self.path, "commit", "-m", message, "-m",
                "Co-Authored-By: Paperclip <noreply@paperclip.ing>")
        git(self.path, "push", "origin", "HEAD:refs/heads/main")
        self.clean()
        return self.parity()

    def hashes(self, year, day):
        # Include shared utilities/build settings and the assigned puzzle.
        files = git(self.path, "ls-files", "--", str(year)).splitlines()
        def relevant(name):
            if "/problems/" in name or name.endswith("/Main.scala"):
                return False
            match = re.search(r"/(?:Day|day)(\d\d)(?:[^0-9]|$)", name)
            return not match or int(match[1]) == day
        return {name: digest((self.path / name).read_bytes()) for name in files if relevant(name)}

    def validate_receipt(self, receipt):
        if receipt.get("schema") != 1 or not receipt.get("owner"):
            raise Blocked("Untrusted publication receipt")
        if not receipt.get("files") or receipt["files"] != self.hashes(receipt["year"], receipt["day"]):
            raise Blocked("Publication inputs/build/source changed")
        for field in ("formatting", "tests", "runner"):
            if receipt.get(field) != "passed":
                raise Blocked("Publication verification incomplete")
        git(self.path, "merge-base", "--is-ancestor", receipt["commit"], "origin/main")

    def bootstrap(self, year):
        target = self.path / str(year)
        if target.exists():
            if target.is_symlink() or not (target / "build.sbt").is_file():
                raise Blocked("Existing year is not a normal sbt project")
            return
        template = self.path / "0000"
        if not (template / "build.sbt").is_file():
            raise Blocked("Missing 0000 template; initialize repository from scala3-aoc template")
        template_files = git(self.path, "ls-files", "--", "0000").splitlines()
        shutil.copytree(template, target, ignore=shutil.ignore_patterns(
            "target", ".bsp", ".bloop", ".metals"))
        for path in sorted(target.rglob("*"), reverse=True):
            if path.is_file():
                try:
                    path.write_text(path.read_text().replace("aoc0000", f"aoc{year}").replace(
                        "scala3-aoc-0000", f"scala3-aoc-{year}"))
                except UnicodeDecodeError:
                    raise Blocked("Unexpected binary file in year template") from None
            if path.name == "aoc0000":
                path.rename(path.with_name(f"aoc{year}"))
        from publication import check_tests
        output = command(target, ["sbt", "--server", "--batch",
            f"scalafmtAll; scalafixAll --check; compile; testOnly aoc{year}.day00.Day00Test; runMain aoc{year}.Main"])
        check_tests(output, 0)
        if "Day00 - part1:" not in output:
            raise Blocked("Year bootstrap did not execute template runner")
        files = [(str(year) + name[len("0000"):]).replace("aoc0000", f"aoc{year}") for name in template_files]
        workflow = self.path / ".github/workflows/ci.yml"
        if not workflow.exists():
            workflow.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(__file__).resolve().parent.parent / "assets/ci.yml", workflow)
            files.append(".github/workflows/ci.yml")
        if workflow.exists():
            import ast
            text = workflow.read_text()
            match = re.search(r"year:\s*(\[[^\]]*\])", text)
            if not match:
                raise Blocked("Cannot safely update existing CI year matrix")
            years = ast.literal_eval(match[1])
            if str(year) not in years:
                years.append(str(year))
                workflow.write_text(text[:match.start(1)] + repr(sorted(years)) + text[match.end(1):])
                files.append(".github/workflows/ci.yml")
        self.commit(files, f"Initialize {year} from 0000", force=True)


def load_progress(repo, account):
    value = read_json(repo.path / ".aoc/progress.json", {"schema": 1, "account": account, "parts": {}})
    if value.get("schema") != 1 or value.get("account") != account or not isinstance(value.get("parts"), dict):
        raise Blocked("Progress schema/account mismatch; reconstruct explicitly")
    return value


def save_progress(repo, progress):
    write_json(repo.path / ".aoc/progress.json", progress)
    repo.commit([".aoc/progress.json"], "Record verified AoC completion")
