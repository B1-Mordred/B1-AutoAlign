#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ -x "$repo_dir/.venv/bin/python" ]]; then
    b1_python="$repo_dir/.venv/bin/python"
else
    b1_python=python3
fi

export PYTHONPATH="$repo_dir/app${PYTHONPATH:+:$PYTHONPATH}"
exec "$b1_python" -m b1_autoalign "$@"
