import os
import re
import shutil
import time

APP_PATH = "app.py"
NEW_VERSION = "2026.05.11-gapday-full-1"


def replace_once(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"Patch point not found: {label}")
    return text.replace(old, new, 1)


with open(APP_PATH, "r", encoding="utf-8") as file:
    source = file.read()

backup = f"app.py.bak_gapday_full_{time.strftime('%Y%m%d_%H%M%S')}"
shutil.copy2(APP_PATH, backup)

source = re.sub(
    r'SERVER_VERSION = "[^"]+"',
    f'SERVER_VERSION = "{NEW_VERSION}"',
    source,
    count=1,
)

source = replace_once(
    source,
    "    ce_full_core = ce_half_core and ce_orb_ok\n    pe_full_core = pe_half_core and pe_orb_ok\n",
    "    # Gap-day mode: ORB is ignored, so a 4/5 HALF core becomes FULL amount.\n    ce_full_core = ce_half_core and (ce_orb_ok or gap_day)\n    pe_full_core = pe_half_core and (pe_orb_ok or gap_day)\n",
    "gap day full core",
)

source = replace_once(
    source,
    '            reason = f"Full {signal}: VWAP + Supertrend + candle momentum + EMA, plus ORB"\n',
    '            if gap_day:\n                reason = f"Full {signal}: VWAP + Supertrend + candle momentum + EMA | Gap day ORB OFF; using FULL amount"\n            else:\n                reason = f"Full {signal}: VWAP + Supertrend + candle momentum + EMA, plus ORB"\n',
    "full reason",
)

source = source.replace(
    "Gap day ORB OFF; FULL disabled",
    "Gap day ORB OFF; FULL amount enabled",
)
source = source.replace(
    "Gap Day: ORB OFF, FULL disabled; strict HALF only",
    "Gap Day: ORB OFF; 4/5 core setup uses FULL amount",
)

with open(APP_PATH, "w", encoding="utf-8") as file:
    file.write(source)

print(f"PATCH_OK {NEW_VERSION} backup={backup}")
