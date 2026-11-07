#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
b1_fqbn=${B1_FQBN:-esp32:esp32:esp32}

arduino-cli compile --fqbn "$b1_fqbn" "$repo_dir/firmware/B1-AutoAlign"
