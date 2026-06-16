#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_PATH="/etc/systemd/system/optionking-cloud.service"

sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip
sudo timedatectl set-timezone Asia/Kolkata || true

cd "$APP_DIR"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip wheel setuptools
pip install -r requirements.txt

if [ ! -f config.json ]; then
  cp config.example.json config.json
  echo "Created config.json. Fill Angel details before starting service."
fi

sudo tee "$SERVICE_PATH" >/dev/null <<EOF
[Unit]
Description=Option King AI Cloud Paper Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/app.py
Restart=always
RestartSec=10
User=$USER
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable optionking-cloud

echo "Setup complete."
echo "Edit config.json, then run:"
echo "  sudo systemctl start optionking-cloud"
echo "  sudo systemctl status optionking-cloud"
