#!/data/data/com.termux/files/usr/bin/bash
set -e

termux-wake-lock || true
echo "Option King AI mobile server starting..."
echo "Local phone URL:"
echo "  http://127.0.0.1:8765"
echo "Same WiFi URL:"
ip -4 addr show wlan0 2>/dev/null | awk '/inet / {split($2,a,"/"); print "  http://" a[1] ":8765"}' || true

if [ "${OPTIONKING_SINGLE_USER:-0}" = "1" ]; then
  echo "Single-user mode forced by OPTIONKING_SINGLE_USER=1"
  python app.py
else
  echo "Multi-user gateway mode"
  python multi_user_gateway.py
fi
