#!/data/data/com.termux/files/usr/bin/bash
cd /sdcard/Download/cloud_bot || exit 1
echo "$(date '+%F %T') | watchdog started" >> watchdog.log

while true; do
  termux-wake-lock >/dev/null 2>&1 || true

  if ! pgrep -f "sshd.*8022" >/dev/null 2>&1; then
    pkill sshd >/dev/null 2>&1 || true
    sshd -p 8022 >/dev/null 2>&1 || true
    echo "$(date '+%F %T') | sshd restarted" >> watchdog.log
  fi

  if ! pgrep -f "python.*app.py" >/dev/null 2>&1; then
    nohup python app.py >> server.log 2>&1 &
    echo "$(date '+%F %T') | app restarted" >> watchdog.log
  fi

  sleep 60
done
