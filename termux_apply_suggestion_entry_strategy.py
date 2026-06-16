import os
import re
import shutil
import time

APP_PATH = "app.py"
NEW_VERSION = "2026.05.11-suggestion-entry-1"


def replace_once(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"Patch point not found: {label}")
    return text.replace(old, new, 1)


with open(APP_PATH, "r", encoding="utf-8") as file:
    source = file.read()

backup = f"app.py.bak_suggestion_entry_{time.strftime('%Y%m%d_%H%M%S')}"
shutil.copy2(APP_PATH, backup)

source = re.sub(
    r'SERVER_VERSION = "[^"]+"',
    f'SERVER_VERSION = "{NEW_VERSION}"',
    source,
    count=1,
)

old_choppy = """    if ema_gap < MIN_EMA_GAP_POINTS and vwap_distance < MIN_VWAP_DISTANCE_POINTS:
        return None, "NONE", 0, "Choppy market: EMA/VWAP too close"

    ce_momentum = has_strong_two_candle_momentum(c1, c2, "CE")
    pe_momentum = has_strong_two_candle_momentum(c1, c2, "PE")
"""

new_choppy = """    choppy_warning = ema_gap < MIN_EMA_GAP_POINTS and vwap_distance < MIN_VWAP_DISTANCE_POINTS
    if choppy_warning and max(ce_score, pe_score) < 4:
        return None, "NONE", 0, "Choppy market: EMA/VWAP too close"

    ce_momentum = has_strong_two_candle_momentum(c1, c2, "CE")
    pe_momentum = has_strong_two_candle_momentum(c1, c2, "PE")
"""
source = replace_once(source, old_choppy, new_choppy, "relax choppy block for 4/5 suggestion")

old_gap = """    gap_up_pe_sustain = (
        (not gap_day)
        or gap_day_direction != "GAP UP"
        or (pe_vwap and pe_supertrend and pe_trend and float(c1.get("close", price)) < vwap and float(c2.get("close", price)) < vwap)
    )
    gap_down_ce_sustain = (
        (not gap_day)
        or gap_day_direction != "GAP DOWN"
        or (ce_vwap and ce_supertrend and ce_trend and float(c1.get("close", price)) > vwap and float(c2.get("close", price)) > vwap)
    )
    ce_half_core = ce_vwap and ce_supertrend and ce_momentum and ce_trend and gap_down_ce_sustain
    pe_half_core = pe_vwap and pe_supertrend and pe_momentum and pe_trend and gap_up_pe_sustain
"""

new_gap = """    raw_gap_up_pe_sustain = (
        (not gap_day)
        or gap_day_direction != "GAP UP"
        or (pe_vwap and pe_supertrend and pe_trend and float(c1.get("close", price)) < vwap and float(c2.get("close", price)) < vwap)
    )
    raw_gap_down_ce_sustain = (
        (not gap_day)
        or gap_day_direction != "GAP DOWN"
        or (ce_vwap and ce_supertrend and ce_trend and float(c1.get("close", price)) > vwap and float(c2.get("close", price)) > vwap)
    )
    # Suggestion-entry mode: a 4/5 HALF setup should be tradable even on a gap day.
    # The old gap sustain check is kept as a warning in the reason, not a hard block.
    gap_up_pe_sustain = True
    gap_down_ce_sustain = True
    ce_half_core = ce_vwap and ce_supertrend and ce_momentum and ce_trend and gap_down_ce_sustain
    pe_half_core = pe_vwap and pe_supertrend and pe_momentum and pe_trend and gap_up_pe_sustain
"""
source = replace_once(source, old_gap, new_gap, "relax gap sustain block")

old_reason = """            elif gap_day:
                reason += " | Gap day ORB OFF; FULL disabled"
"""

new_reason = """            elif gap_day:
                reason += " | Gap day ORB OFF; FULL disabled"
            if gap_day and signal == "CE" and gap_day_direction == "GAP DOWN" and not raw_gap_down_ce_sustain:
                reason += " | GAP-DOWN CE sustain relaxed"
            if gap_day and signal == "PE" and gap_day_direction == "GAP UP" and not raw_gap_up_pe_sustain:
                reason += " | GAP-UP PE sustain relaxed"
            if choppy_warning:
                reason += " | Choppy warning ignored because score is 4/5+"
"""
source = replace_once(source, old_reason, new_reason, "add relaxed warning to trade reason")

with open(APP_PATH, "w", encoding="utf-8") as file:
    file.write(source)

print(f"PATCH_OK {NEW_VERSION} backup={backup}")
