#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 /dev/serial/by-id/..." >&2
    exit 2
fi

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
b1_port=$1
b1_fqbn=${B1_FQBN:-esp32:esp32:esp32}
b1_baud=${B1_UPLOAD_BAUD:-460800}
b1_output_dir="$repo_dir/build/firmware-manual"

if [[ ! -e $b1_port ]]; then
    echo "Serial device does not exist: $b1_port" >&2
    exit 2
fi

arduino-cli compile --fqbn "$b1_fqbn" --output-dir "$b1_output_dir" \
    "$repo_dir/firmware/B1-AutoAlign"

b1_binary="$b1_output_dir/B1-AutoAlign.ino.bin"
if [[ ! -f $b1_binary ]]; then
    echo "Compiled application binary not found: $b1_binary" >&2
    exit 2
fi

declare -a b1_esptool_command
if [[ -n ${B1_ESPTOOL:-} ]]; then
    if [[ ! -x $B1_ESPTOOL ]]; then
        echo "B1_ESPTOOL is not executable: $B1_ESPTOOL" >&2
        exit 2
    fi
    b1_esptool_command=("$B1_ESPTOOL")
elif command -v esptool >/dev/null 2>&1; then
    b1_esptool_command=(esptool)
elif command -v esptool.py >/dev/null 2>&1; then
    b1_esptool_command=(esptool.py)
elif python3 -c 'import esptool' >/dev/null 2>&1; then
    b1_esptool_command=(python3 -m esptool)
else
    b1_bundled_esptool=""
    if [[ -d $HOME/.arduino15/packages/esp32/tools/esptool_py ]]; then
        while IFS= read -r b1_candidate; do
            b1_bundled_esptool=$b1_candidate
        done < <(find "$HOME/.arduino15/packages/esp32/tools/esptool_py" \
            -mindepth 2 -maxdepth 2 -type f -name esptool -perm -u+x -print | sort -V)
    fi
    if [[ -z $b1_bundled_esptool ]]; then
        echo "esptool is required for manual flashing" >&2
        exit 2
    fi
    b1_esptool_command=("$b1_bundled_esptool")
fi

"${b1_esptool_command[@]}" --chip esp32 --port "$b1_port" --baud "$b1_baud" \
    --before no-reset --after no-reset \
    write_flash 0x00010000 "$b1_binary"

echo "Application verified. Tap EN/RESET without holding BOOT to start it."
