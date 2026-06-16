#!/data/data/com.termux/files/usr/bin/bash
set -e

BOOT_DIR="$HOME/.termux/boot"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$BOOT_DIR"

cat > "$BOOT_DIR/optionking_server.sh" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock || true
cd "$APP_DIR"
bash termux_start.sh >> "$APP_DIR/termux_server.log" 2>&1
EOF

chmod +x "$BOOT_DIR/optionking_server.sh"

echo "Boot script installed."
echo "Install Termux:Boot from F-Droid, open it once, then restart phone."
echo "Server log:"
echo "  $APP_DIR/termux_server.log"
