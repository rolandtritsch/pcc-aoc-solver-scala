"""Small shared contracts; no model-dependent workflow decisions."""
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import signal
import tempfile
import time
import re


class Blocked(RuntimeError):
    pass


class LockContention(Blocked):
    """Another agent is still legitimately busy (e.g. a long Solver run) --
    not a semantic failure, nothing is actually broken. Callers must not
    treat this like a genuine Blocked: no state should be mutated, so a
    later continuation simply sees the unchanged, still-valid state."""


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else
                          json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default
    except (ValueError, UnicodeError) as error:
        raise Blocked(f"Corrupt JSON: {path}; reconstruct explicitly") from error


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    with open(temporary, "w", opener=lambda p, flags: os.open(p, flags, 0o600)) as out:
        json.dump(value, out, indent=2, sort_keys=True)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    temporary.replace(path)


def command(cwd, args, timeout=900):
    # Retain a live private diagnostic during slow builds, without putting
    # arbitrary command stderr (possibly credential-bearing) into task comments.
    diagnostic = Path(os.environ.get("AOC_DIAGNOSTICS", "/tmp/aoc-diagnostics"))
    diagnostic.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w+", dir=diagnostic, suffix=".log", delete=False) as log:
        path = Path(log.name)
        if args[0] == "sbt":
            print(json.dumps({"type": "text", "part": {"type": "text", "text":
                "Verifying Scala project; live private diagnostic " + str(path)}}), flush=True)
        process = subprocess.Popen(args, cwd=cwd, text=True, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise Blocked(f"{args[0]} timed out; private diagnostic {path}") from None
        if process.returncode:
            raise Blocked(f"{args[0]} failed ({process.returncode}); private diagnostic {path}")
        log.seek(0)
        output = log.read()
    path.unlink()
    # Leading spaces in Git porcelain are status columns, not decoration.
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", output).rstrip("\r\n")


def git(repo, *args):
    return command(repo, ["git", *args], 120)


def identity(year, day, part):
    if type(year) is not int or type(day) is not int or type(part) is not int:
        raise Blocked("Puzzle identity must contain integers")
    if not (2015 <= year <= 2025 and 1 <= day <= days(year) and part in (1, 2)):
        raise Blocked("Puzzle identity outside configured calendar")
    return f"{year}/{day:02}/{part}"


def days(year):
    return 12 if year == 2025 else 25


def calendar():
    return [(y, d, p) for y in range(2015, 2026)
            for d in range(1, days(y) + 1) for p in (1, 2)]


def finale(year, day, part):
    return day == days(year) and part == 2


LOCK_ATTEMPTS = 6


@contextlib.contextmanager
def lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with open(root / ".mutation.lock", "a") as handle:
        for attempt in range(LOCK_ATTEMPTS):
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as error:
                if attempt == LOCK_ATTEMPTS - 1:
                    raise LockContention("Another company mutation is active; retry later") from error
                # This company's own agents run short mutations; a brief
                # overlap should self-clear well within this bounded wait.
                time.sleep(attempt + random.uniform(0, 0.5))
        yield
