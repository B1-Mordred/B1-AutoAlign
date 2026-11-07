#!/usr/bin/env bash
set -euo pipefail

b1_data_home=${XDG_DATA_HOME:-"$HOME/.local/share"}
rm -f -- \
    "$HOME/.local/bin/b1-autoalign" \
    "$b1_data_home/applications/b1-autoalign.desktop" \
    "$b1_data_home/icons/hicolor/scalable/apps/b1-autoalign.svg"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$b1_data_home/applications" >/dev/null 2>&1 || true
fi

echo "Removed B1-AutoAlign desktop launcher."
