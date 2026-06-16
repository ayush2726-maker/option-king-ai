#!/data/data/com.termux/files/usr/bin/bash
cd /sdcard/Download/cloud_bot || exit 1
termux-wake-lock >/dev/null 2>&1 || true

if ! pgrep -f "sshd.*8022" >/dev/null 2>&1; then
  pkill sshd >/dev/null 2>&1 || true
  sshd -p 8022 >/dev/null 2>&1 || true
fi

python - <<'PY' >/dev/null 2>&1 || true
import json
p='config.json'
cfg=json.load(open(p))
cfg['auto_update_enabled']=True
cfg['auto_start_bot']=True
cfg['mute_feed_safety_telegram_alerts']=True
cfg['host']='0.0.0.0'
cfg['port']=8765
open(p,'w').write(json.dumps(cfg, indent=2))
PY

if ! pgrep -f "python.*app.py" >/dev/null 2>&1; then
  nohup python app.py >> server.log 2>&1 &
  echo "$(date '+%F %T') | server started" >> watchdog.log
fi
