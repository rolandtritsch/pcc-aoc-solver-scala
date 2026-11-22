#!/bin/bash
set -euo pipefail
export JAVA_HOME=/opt/java
# Preserve the run-scoped Git credential broker before ordinary tools.
export PATH="${PATH:-/usr/local/bin:/usr/bin:/bin}:/opt/java/bin:/opt/sbt/bin"
exec python3 /opt/aoc-runtime/launch.py "$@"
