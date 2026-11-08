#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: $0 /dev/serial/by-id/... [output.bin]" >&2
    exit 2
fi

b1_port=$1
b1_output=${2:-"b1-autoalign-backup-$(date +%Y%m%d-%H%M%S).bin"}
b1_size=${B1_FLASH_SIZE_BYTES:-0x400000}
b1_baud=${B1_BACKUP_BAUD:-460800}
b1_before=${B1_ESPTOOL_BEFORE:-default-reset}
b1_after=${B1_ESPTOOL_AFTER:-hard-reset}

if [[ ! -e "$b1_port" ]]; then
    echo "Serial device does not exist: $b1_port" >&2
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
        echo "esptool is required for flash backup" >&2
        exit 2
    fi
    b1_esptool_command=("$b1_bundled_esptool")
fi

"${b1_esptool_command[@]}" --chip esp32 --port "$b1_port" --baud "$b1_baud" \
    --before "$b1_before" --after "$b1_after" \
    read_flash 0x000000 "$b1_size" "$b1_output"

sha256sum "$b1_output"
