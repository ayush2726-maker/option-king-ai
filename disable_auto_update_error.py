import json
import os

CONFIG = "config.json"

if not os.path.exists(CONFIG):
    raise SystemExit("config.json not found. Run this from /sdcard/Download/cloud_bot")

with open(CONFIG, "r", encoding="utf-8") as file:
    cfg = json.load(file)

cfg["auto_update_enabled"] = False
cfg["auto_update_interval_seconds"] = 86400
cfg["update_manifest_urls"] = []

with open(CONFIG, "w", encoding="utf-8") as file:
    json.dump(cfg, file, indent=2)

print("Auto-update disabled OK. Restart server now.")
