import json, zipfile, os
backup = 'data/backups/OptionKingAI_cloud_bot_backup_20260527_214446.zip'
keys = ['api_key','client_id','password','totp_secret','telegram_token','chat_id','api_auth_token','capital']
with zipfile.ZipFile(backup) as z:
    old = json.loads(z.read('config.json').decode('utf-8'))
cur = {}
if os.path.exists('config.json'):
    try:
        cur = json.load(open('config.json'))
    except Exception:
        cur = {}
for key in keys:
    if str(old.get(key) or '').strip():
        cur[key] = old[key]
with open('config.json', 'w') as f:
    json.dump(cur, f, indent=2)
print('restored_keys', ','.join([k for k in keys if str(cur.get(k) or '').strip()]))
