#!/data/data/com.termux/files/usr/bin/bash
set -e

cd "$(dirname "$0")"
python multi_user_gateway.py --add-user
