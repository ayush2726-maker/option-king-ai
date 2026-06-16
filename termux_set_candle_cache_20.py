import re
import shutil
import time

APP_PATH = "app.py"
NEW_VERSION = "2026.05.12-cache20-1"

with open(APP_PATH, "r", encoding="utf-8") as file:
    source = file.read()

backup = f"app.py.bak_cache20_{time.strftime('%Y%m%d_%H%M%S')}"
shutil.copy2(APP_PATH, backup)

source = re.sub(r'SERVER_VERSION = "[^"]+"', f'SERVER_VERSION = "{NEW_VERSION}"', source, count=1)
source = re.sub(r"CANDLE_CACHE_SECONDS = \d+", "CANDLE_CACHE_SECONDS = 20", source, count=1)

with open(APP_PATH, "w", encoding="utf-8") as file:
    file.write(source)

print(f"PATCH_OK {NEW_VERSION} backup={backup}")
