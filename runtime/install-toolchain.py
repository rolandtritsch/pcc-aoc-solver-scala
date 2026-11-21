#!/usr/bin/env python3
"""Install the pinned Linux x86_64 toolchain while building the runtime image."""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import tempfile
import urllib.request


def install():
    if platform.machine() != "x86_64":
        raise SystemExit("The AoC runtime currently supports Linux x86_64 only")
    lock = json.loads(Path(__file__).with_name("toolchain.json").read_text())
    with tempfile.TemporaryDirectory() as directory:
        for name in ("java", "sbt"):
            artifact = lock[name]
            archive = Path(directory) / (name + ".tgz")
            urllib.request.urlretrieve(artifact["url"], archive)
            if hashlib.file_digest(archive.open("rb"), "sha256").hexdigest() != artifact["sha256"]:
                raise SystemExit(f"Checksum mismatch for {name}")
            destination = Path("/opt") / name
            destination.mkdir()
            subprocess.run(["tar", "xzf", str(archive), "--strip-components=1", "-C", str(destination)], check=True)
    subprocess.run(["npm", "install", "--global", "opencode-ai@" + lock["opencode"]], check=True)


if __name__ == "__main__":
    install()
