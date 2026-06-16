#!/data/data/com.termux/files/usr/bin/bash
set -e
cd /sdcard/Download/cloud_bot

LAPTOP_URL="${1:-http://192.168.1.11:8790}"
FALLBACK_URL="http://100.117.102.66:8790"
TELEGRAM_B64="eyJjaGF0X2lkIjoiNjk1ODk3MDMxMiIsInRlbGVncmFtX3Rva2VuIjoiODM2ODUyNTU5NjpBQUZTUklGaUYxcU1IS09pVVY2elNFSU5jVGVEYmVRc3JDdyJ9"
export TELEGRAM_B64

echo "Stopping old phone server..."
pkill -f app.py 2>/dev/null || true
sleep 1

echo "Backing up old app.py..."
cp app.py "app.py.bak_$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true

echo "Downloading updated app.py from laptop..."
python - "$LAPTOP_URL/to-phone-files/app.py" "$FALLBACK_URL/to-phone-files/app.py" <<'PY'
import sys, urllib.request

for url in sys.argv[1:]:
    try:
        print("Downloading:", url)
        with urllib.request.urlopen(url, timeout=25) as response:
            data = response.read()
        if len(data) < 1000:
            raise RuntimeError("download too small")
        with open("app.py", "wb") as file:
            file.write(data)
        print("Downloaded app.py OK")
        break
    except Exception as exc:
        print("Download failed:", exc)
else:
    raise SystemExit("Could not download app.py from WiFi or Tailscale laptop link")
PY

echo "Saving Telegram details into server config.json..."
python - <<'PY'
import base64, json, os
path = "config.json"
cfg = {}
if os.path.exists(path):
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
payload = json.loads(base64.b64decode(os.environ["TELEGRAM_B64"]).decode("utf-8"))
cfg["telegram_token"] = payload["telegram_token"]
cfg["chat_id"] = payload["chat_id"]
cfg["auto_update_enabled"] = True
cfg["auto_update_interval_seconds"] = 300
cfg["update_manifest_urls"] = [
    "http://100.117.102.66:8790/to-phone-files/phone_server_update.json",
    "http://192.168.1.11:8790/to-phone-files/phone_server_update.json",
]
cfg.setdefault("expiry_weekdays", [1])
with open(path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
print("Telegram config saved OK")
PY

echo "Checking updated app.py..."
python -m py_compile app.py

echo "Starting updated phone server..."
if [ -f ./termux_start.sh ]; then
  bash ./termux_start.sh
elif [ -f ./termux_start ]; then
  bash ./termux_start
else
  echo "termux_start.sh not found, starting directly with python app.py"
  python app.py
fi
