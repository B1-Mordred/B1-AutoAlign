#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 /dev/serial/by-id/..." >&2
    exit 2
fi

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
b1_port=$1
b1_fqbn=${B1_FQBN:-esp32:esp32:esp32:UploadSpeed=460800}

if [[ ! -e "$b1_port" ]]; then
    echo "Serial device does not exist: $b1_port" >&2
    exit 2
fi

arduino-cli upload --port "$b1_port" --fqbn "$b1_fqbn" "$repo_dir/firmware/B1-AutoAlign"
