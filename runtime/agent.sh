#!/bin/bash
set -euo pipefail
export JAVA_HOME=/opt/java
# Preserve Paperclip's run-scoped Git credential broker ahead of the real tools.
export PATH="${PATH:-/usr/local/bin:/usr/bin:/bin}:/opt/java/bin:/opt/sbt/bin"
export AOC_COMPANY_PACKAGE_DIR=/opt/aoc-company
export AOC_OPENCODE_BINARY=/usr/local/bin/opencode
export AOC_REPO_DIR="$PWD"
if [[ -n "${AOC_PAPERCLIP_API_URL:-}" ]]; then
    export PAPERCLIP_API_URL="$AOC_PAPERCLIP_API_URL"
fi

# Paperclip stages a detached checkout without remotes on the SSH target.
# Publishing is an explicit company action, so prepare its known GitHub remote.
if [[ "${1:-}" == run && -f 0000/project/build.properties ]] && git rev-parse --git-dir >/dev/null 2>&1; then
    expected=https://github.com/rolandtritsch/scala3-aoc.git
    if git remote get-url origin >/dev/null 2>&1; then
        [[ "$(git remote get-url origin)" == "$expected" ]] || { echo 'Unexpected solution origin' >&2; exit 1; }
    else
        git remote add origin "$expected"
    fi
    if ! git symbolic-ref -q HEAD >/dev/null; then
        git branch -f main HEAD
        git symbolic-ref HEAD refs/heads/main
    fi
    git config credential.https://github.com.helper '!gh auth git-credential'
    git config user.name 'AoC Solver'
    git config user.email 'aoc-solver@users.noreply.github.com'
    git fetch origin main
fi

case "$(basename "$0")" in
    aoc-cto) exec python3 "$AOC_COMPANY_PACKAGE_DIR/skills/aoc-workflow/scripts/aoc_cto.py" "$@" ;;
    *) exec /usr/local/bin/opencode "$@" ;;
esac
