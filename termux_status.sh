#!/data/data/com.termux/files/usr/bin/bash
set -e

echo "Option King AI server URLs"
echo ""
echo "Same phone:"
echo "  http://127.0.0.1:8765"
echo ""
echo "Same WiFi:"
ip -4 addr show wlan0 2>/dev/null | awk '/inet / {split($2,a,"/"); print "  http://" a[1] ":8765"}' || echo "  WiFi IP not found"
echo ""
echo "Server test:"
curl -s -H "X-Api-Token: $(python - <<'PY'
import json
try:
    print(json.load(open("config.json")).get("api_auth_token", "optionking-local"))
except Exception:
    print("optionking-local")
PY
)" http://127.0.0.1:8765/status || echo "Server not responding"
