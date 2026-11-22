"""Only authorized solution paths, actual tests, exact runner answers."""
import re

from common import Blocked, command, git, identity, now


def check_output(output, year, day, part, answer=None):
    suite = f"aoc{year}.Day{day:02}Test:"
    if suite not in output:
        raise Blocked("Assigned day suite did not run")
    section = output.split(suite, 1)[1].split("[success]", 1)[0]
    if not re.search(r"Passed: Total [1-9]\d*, Failed 0, Errors 0", section):
        raise Blocked("No positive active passing assigned-day tests")
    answers = re.findall(rf"^Day{day:02} - part{part}:\s*(.+?)\s*$", output, re.M)
    if len(answers) != 1 or (answer is not None and answers[0] != answer):
        raise Blocked("Requested runner answer absent, ambiguous, or mismatched")
    return answers[0]


def verify(repo, year, day, part, answer=None):
    identity(year, day, part)
    project = repo.path / str(year)
    if project.is_symlink() or not (project / "build.sbt").is_file():
        raise Blocked("Year is not a normal sbt project")
    repo.clean()
    repo.parity()
    repo.assert_owner()
    before = git(repo.path, "rev-parse", "HEAD")
    output = command(project, ["sbt", "--server", "--batch",
        f"scalafmtCheckAll; scalafmtSbtCheck; testOnly aoc{year}.Day{day:02}Test; testOnly *; run"])
    answer = check_output(output, year, day, part, answer)
    repo.clean()
    if repo.parity() != before:
        raise Blocked("Repository changed during verification")
    return {"schema": 1, "year": year, "day": day, "part": part, "answer": answer,
            "commit": before, "files": repo.hashes(year, day), "owner": repo.owner,
            "formatting": "passed", "tests": "passed", "runner": "passed", "verifiedAt": now()}


def allowed_files(year, day):
    prefix = f"{year}/"
    return {prefix + name for name in (
        f"src/main/scala/aoc{year}/Day{day:02}.scala",
        f"src/test/scala/aoc{year}/Day{day:02}Test.scala",
        f"src/main/resources/inputs/Day{day:02}Test.txt",
        f"src/main/scala/aoc{year}/Main.scala")}


def publish(repo, assignment, answer, files):
    year, day, part = (assignment[k] for k in ("year", "day", "part"))
    identity(year, day, part)
    prefix = f"{year}/"
    allowed = allowed_files(year, day)
    if not files or not set(files) <= allowed:
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
    output = command(repo.path / str(year), ["sbt", "--server", "--batch",
        f"scalafmtAll; scalafmtCheckAll; scalafmtSbtCheck; testOnly aoc{year}.Day{day:02}Test; testOnly *; run"])
    check_output(output, year, day, part, answer)
    repo.commit(files, f"{year} Day{day:02}: solve part {part}")
    return verify(repo, year, day, part, answer)
