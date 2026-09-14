#!/usr/bin/env bash
# Adds "AI Stock Radar" to the Ubuntu app launcher (current user only).
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${XDG_DATA_HOME:-$HOME/.local/share}/applications/ai-stock-radar.desktop"
ICON="$APP_DIR/scripts/icon.svg"

mkdir -p "$(dirname "$TARGET")"
cat > "$ICON" <<'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="14" fill="#2f5fd0"/><path d="M8 20l5-5 4 3 7-8" stroke="white" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
SVG

cat > "$TARGET" <<EOF
[Desktop Entry]
Type=Application
Name=AI Stock Radar
Comment=Taiwan & US AI stock predictions driven by real news
Exec=$APP_DIR/run.sh
Icon=$ICON
Terminal=false
Categories=Office;Finance;
EOF
chmod +x "$TARGET"
echo "Installed launcher: $TARGET"
