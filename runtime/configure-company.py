#!/usr/bin/env python3
"""Compatibility entry point for the unified operator CLI environment command."""
from pathlib import Path
import subprocess
import sys

if __name__ == "__main__":
    command = Path(__file__).resolve().parent.parent / "operators/aoc.py"
    args = ["--company" if value == "--company-id" else value for value in sys.argv[1:]]
    raise SystemExit(subprocess.call([sys.executable, str(command), "environment", "apply", *args]))
