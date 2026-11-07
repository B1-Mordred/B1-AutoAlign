#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
b1_user_bin="$HOME/.local/bin"
b1_data_home=${XDG_DATA_HOME:-"$HOME/.local/share"}
b1_app_dir="$b1_data_home/applications"
b1_icon_dir="$b1_data_home/icons/hicolor/scalable/apps"
b1_temp_dir=$(mktemp -d)
trap 'rm -rf -- "$b1_temp_dir"' EXIT

if [[ -x "$repo_dir/.venv/bin/python" ]]; then
    b1_python="$repo_dir/.venv/bin/python"
else
    b1_python=python3
fi

if ! "$b1_python" -c 'import PyQt6, serial' >/dev/null 2>&1; then
    echo "PyQt6 and pyserial are required. Run $repo_dir/scripts/setup-app.sh first." >&2
    exit 2
fi

mkdir -p "$b1_user_bin" "$b1_app_dir" "$b1_icon_dir"
sed "s|@REPO_DIR@|$repo_dir|g" \
    "$repo_dir/packaging/b1-autoalign-launcher.in" > "$b1_temp_dir/b1-autoalign"
sed "s|@USER_BIN@|$b1_user_bin|g" \
    "$repo_dir/packaging/b1-autoalign.desktop.in" > "$b1_temp_dir/b1-autoalign.desktop"

install -m 0755 "$b1_temp_dir/b1-autoalign" "$b1_user_bin/b1-autoalign"
install -m 0644 "$b1_temp_dir/b1-autoalign.desktop" "$b1_app_dir/b1-autoalign.desktop"
install -m 0644 "$repo_dir/assets/b1-autoalign.svg" "$b1_icon_dir/b1-autoalign.svg"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$b1_app_dir" >/dev/null 2>&1 || true
fi

echo "Installed B1-AutoAlign desktop launcher."
