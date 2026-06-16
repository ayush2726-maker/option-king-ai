import json

path = "config.json"
with open(path, "r", encoding="utf-8") as file:
    cfg = json.load(file)

cfg["auto_update_enabled"] = False
cfg["update_manifest_urls"] = []
cfg["auto_update_interval_seconds"] = 86400

with open(path, "w", encoding="utf-8") as file:
    json.dump(cfg, file, indent=2)

print("CONFIG_OK")
