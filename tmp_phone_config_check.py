import json, os
for path in ["config.json", "/sdcard/Download/cloud_bot/config.json", os.path.expanduser("~/config.json")]:
    if os.path.exists(path):
        cfg = json.load(open(path))
        print(path)
        for k in ["api_key", "client_id", "password", "totp_secret", "telegram_token", "chat_id", "api_auth_token", "capital"]:
            v = cfg.get(k)
            print(k, "FILLED" if str(v or "").strip() else "BLANK")
