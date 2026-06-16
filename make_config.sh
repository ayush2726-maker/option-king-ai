#!/data/data/com.termux/files/usr/bin/bash
set -e

echo "Option King AI config maker"
echo ""

printf "Angel API Key: "
read -r API_KEY

printf "Client ID: "
read -r CLIENT_ID

printf "Password: "
read -r PASSWORD

printf "TOTP Secret: "
read -r TOTP_SECRET

printf "Mobile App Token [optionking-local]: "
read -r API_AUTH_TOKEN
API_AUTH_TOKEN=${API_AUTH_TOKEN:-optionking-local}

printf "Capital [20000]: "
read -r CAPITAL
CAPITAL=${CAPITAL:-20000}

export API_KEY CLIENT_ID PASSWORD TOTP_SECRET API_AUTH_TOKEN CAPITAL

python - <<'PY'
import json, os

cfg = {
    "api_key": os.environ["API_KEY"],
    "client_id": os.environ["CLIENT_ID"],
    "password": os.environ["PASSWORD"],
    "totp_secret": os.environ["TOTP_SECRET"],
    "telegram_token": "",
    "chat_id": "",
    "api_auth_token": os.environ["API_AUTH_TOKEN"],
    "capital": float(os.environ["CAPITAL"]),
    "auto_start_bot": True,
    "market_timezone": "Asia/Kolkata",
    "market_holidays": [],
    "host": "0.0.0.0",
    "port": 8765
}

with open("config.json", "w") as f:
    json.dump(cfg, f, indent=2)

print("config.json saved OK")
PY

python -m json.tool config.json >/dev/null
echo "config.json valid OK"
