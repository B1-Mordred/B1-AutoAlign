#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

bash -n "$repo_dir/scripts/"*.sh
python3 -m unittest discover -s "$repo_dir/tests" -p 'test_*.py'
python3 -c 'import ast, pathlib; [ast.parse(path.read_text()) for path in pathlib.Path("'"$repo_dir"'").rglob("*.py")]'
b1_config_dir=$(mktemp -d)
trap 'rm -rf -- "$b1_config_dir"' EXIT
g++ -std=c++17 -Wall -Wextra -Werror \
    -I "$repo_dir/tests/firmware_host" \
    -I "$repo_dir/firmware/B1-AutoAlign" \
    "$repo_dir/tests/firmware_host/test_motion_axis.cpp" \
    -o "$b1_config_dir/test_motion_axis"
"$b1_config_dir/test_motion_axis"
QT_QPA_PLATFORM=offscreen XDG_CONFIG_HOME="$b1_config_dir" "$repo_dir/scripts/run-app.sh" --smoke-test
"$repo_dir/scripts/build.sh"
