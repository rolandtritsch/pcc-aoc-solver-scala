"""Only authorized solution paths, actual tests, exact runner answers."""
import re

from common import Blocked, command, git, identity, now

# Process-local only. Callers may supply a tree only after proving a clean
# checkout. Progress-only commits do not change the year's Git tree.
_checked_projects = {}


def check_tests(output, day):
    output = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", output)
    if not re.search(rf"^\+ Day{day:02}\s*$", output, re.M):
        raise Blocked("Assigned day suite did not run")
    summaries = re.findall(r"(\d+) tests passed\. (\d+) tests failed\. (\d+) tests ignored\.", output)
    if len(summaries) != 1 or not int(summaries[0][0]) or any(map(int, summaries[0][1:])):
        raise Blocked("No positive active passing assigned-day tests")


def check_answer(output, day, part, answer=None):
    answers = re.findall(rf"^Day{day:02} - part{part}:\s*(.+?)\s*$", output, re.M)
    if len(answers) != 1 or (answer is not None and answers[0] != answer):
        raise Blocked("Requested runner answer absent, ambiguous, or mismatched")
    return answers[0]


def check_output(output, year, day, part, answer=None):
    check_tests(output, day)
    return check_answer(output, day, part, answer)


def run_checks(project, year, day, verified_tree=None, commit=None):
    # Keep the assigned suite's evidence separate: a green full-year run must
    # never conceal an empty/misnamed testOnly selection.
    key = (str(project.resolve()), year, verified_tree)
    cached = _checked_projects.get(key) if verified_tree else None
    if cached and day in cached["days"]:
        return cached["output"]
    lint = "" if cached else "scalafmtCheckAll; scalafmtSbtCheck; scalafixAll --check; "
    output = command(project, ["sbt", "--server", "--batch",
        lint + f"testOnly aoc{year}.day{day:02}.Day{day:02}Test"])
    check_tests(output, day)
    if cached:
        cached["days"].add(day)
        return cached["output"]
    output = command(project, ["sbt", "--server", "--batch", f"testOnly *; runMain aoc{year}.Main"])
    if verified_tree:
        _checked_projects[key] = {"output": output, "days": {day}, "commit": commit, "at": now()}
    return output


def verify(repo, year, day, part, answer=None):
    identity(year, day, part)
    project = repo.path / str(year)
    if project.is_symlink() or not (project / "build.sbt").is_file():
        raise Blocked("Year is not a normal sbt project")
    repo.clean()
    repo.parity()
    repo.assert_owner()
    before = git(repo.path, "rev-parse", "HEAD")
    tree = git(repo.path, "rev-parse", f"HEAD:{year}")
    output = run_checks(project, year, day, verified_tree=tree, commit=before)
    answer = check_answer(output, day, part, answer)
    repo.clean()
    if repo.parity() != before:
        raise Blocked("Repository changed during verification")
    checks = _checked_projects[(str(project.resolve()), year, tree)]
    return {"schema": 1, "year": year, "day": day, "part": part, "answer": answer,
            "commit": before, "files": repo.hashes(year, day), "owner": repo.owner,
            "verification": {"tree": tree, "yearChecksCommit": checks["commit"], "yearChecksAt": checks["at"]},
            "formatting": "passed", "tests": "passed", "runner": "passed", "verifiedAt": now()}


class AllowedFiles:
    def __init__(self, year, day, part):
        self.part = part
        self.future_part = re.compile(r"Part(\d+)\.scala$")
        self.pattern = re.compile(
            rf"{year}/src/(?:"
            rf"(?:main|test)/scala/aoc{year}/(?:day{day:02}|util)/[A-Za-z][A-Za-z0-9_]*\.scala|"
            rf"main/scala/aoc{year}/Main\.scala|"
            rf"test/resources/inputs/Day{day:02}[A-Za-z0-9_-]*\.txt|"
            rf"main/resources/inputs/Day{day:02}Test[A-Za-z0-9_-]*\.txt)")

    def __contains__(self, name):
        if not isinstance(name, str) or self.pattern.fullmatch(name) is None:
            return False
        future = self.future_part.search(name)
        # Working ahead on a part that hasn't been gathered/assigned yet is
        # not a legitimate publication, even though earlier parts' files may
        # still be refactored as later parts are solved.
        return not future or int(future[1]) <= self.part


def allowed_files(year, day, part):
    identity(year, day, part)
    return AllowedFiles(year, day, part)


def publish(repo, assignment, answer, files):
    year, day, part = (assignment[k] for k in ("year", "day", "part"))
    identity(year, day, part)
    prefix = f"{year}/"
    allowed = allowed_files(year, day, part)
    if not files or not all(name in allowed for name in files):
        raise Blocked("Publication includes unauthorized paths")
    for name in files:
        path = repo.path / name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(repo.path.resolve()):
            raise Blocked("Publication path is missing or escapes checkout")
    repo.assert_owner()
    dirty = {line[3:] for line in git(repo.path, "status", "--porcelain", "-uall").splitlines()}
    if not dirty <= set(files):
        raise Blocked("Unrelated changes preserved")
    scala = [f[len(prefix):] for f in files if f.endswith(".scala")]
    command(repo.path / str(year), ["sbt", "--server", "--batch", "scalafmtOnly " + " ".join(scala)])
    output = run_checks(repo.path / str(year), year, day)
    check_answer(output, day, part, answer)
    repo.commit(files, f"{year} Day{day:02}: solve part {part}")
    return verify(repo, year, day, part, answer)
