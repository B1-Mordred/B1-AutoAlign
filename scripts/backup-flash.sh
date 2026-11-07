#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: $0 /dev/serial/by-id/... [output.bin]" >&2
    exit 2
fi

b1_port=$1
b1_output=${2:-"b1-autoalign-backup-$(date +%Y%m%d-%H%M%S).bin"}
b1_size=${B1_FLASH_SIZE_BYTES:-0x400000}

if [[ ! -e "$b1_port" ]]; then
    echo "Serial device does not exist: $b1_port" >&2
    exit 2
fi

if command -v esptool.py >/dev/null 2>&1; then
    esptool.py --chip esp32 --port "$b1_port" read_flash 0x000000 "$b1_size" "$b1_output"
elif python3 -c 'import esptool' >/dev/null 2>&1; then
    python3 -m esptool --chip esp32 --port "$b1_port" read_flash 0x000000 "$b1_size" "$b1_output"
else
    echo "esptool is required for flash backup" >&2
    exit 2
fi

sha256sum "$b1_output"
