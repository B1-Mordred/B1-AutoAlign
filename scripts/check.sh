#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

bash -n "$repo_dir/scripts/"*.sh
python3 -m unittest discover -s "$repo_dir/tests" -p 'test_*.py'
python3 -c 'import ast, pathlib; ast.parse(pathlib.Path("'"$repo_dir"'/tools/b1_autoalign_cli.py").read_text())'
"$repo_dir/scripts/build.sh"
