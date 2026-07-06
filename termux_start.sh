#!/data/data/com.termux/files/usr/bin/bash
cd /storage/emulated/0/Download/cloud_bot || exit 1

echo "Option King AI PERSONAL bot starting..."
echo "Local phone URL:"
echo "  http://127.0.0.1:8765"
echo "Same WiFi URL:"
IP=$(ip route get 8.8.8.8 2>/dev/null | awk '{print $7; exit}')
if [ -n "$IP" ]; then
  echo "  http://$IP:8765"
else
  echo "  check phone WiFi IP, port 8765"
fi
echo "Token:"
echo "  optionking-local"
echo ""

export PORT=8765
export HOST=127.0.0.1
export OPTIONKING_PERSONAL_MODE=1
export PYTHONUNBUFFERED=1

python app.py
