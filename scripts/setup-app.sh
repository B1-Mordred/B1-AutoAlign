#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

if python3 -c 'import PyQt6, serial' >/dev/null 2>&1; then
    echo "PyQt6 and pyserial are already available. Run: $repo_dir/scripts/run-app.sh"
    exit 0
fi

if ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
    echo "Python venv support is missing. On Debian/Ubuntu install python3-venv, then rerun this script." >&2
    exit 2
fi

python3 -m venv "$repo_dir/.venv"
"$repo_dir/.venv/bin/python" -m pip install --upgrade pip
"$repo_dir/.venv/bin/python" -m pip install --editable "$repo_dir"

echo "Desktop environment ready. Run: $repo_dir/scripts/run-app.sh"
