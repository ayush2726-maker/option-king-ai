#!/data/data/com.termux/files/usr/bin/bash
set -e

pkg update -y
pkg install -y python clang rust openssl libffi git termux-api nano curl
python -m pip install --upgrade pip wheel setuptools
pip install -r requirements.txt

if [ ! -f config.json ]; then
  cp config.example.json config.json
  echo "Created config.json. Fill Angel details before running termux_start.sh"
fi

echo "Termux setup done."
echo "Edit config.json:"
echo "  nano config.json"
echo "Start server:"
echo "  bash termux_start.sh"
