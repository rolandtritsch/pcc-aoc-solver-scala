#!/usr/bin/env python3
"""Review entry point for the shared publication verifier; never publishes."""

import runpy
from pathlib import Path
import sys

if __name__ == "__main__":
    publisher = Path(__file__).resolve().parents[2] / "aoc-solve-scala/scripts/aoc_solver_publish.py"
    sys.argv = [str(publisher), "verify", *sys.argv[1:]]
    runpy.run_path(str(publisher), run_name="__main__")
