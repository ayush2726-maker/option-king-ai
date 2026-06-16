import datetime as dt
import os
import re

APP_PATH = "app.py"
VERSION = "2026.05.09-market-closed-candle-guard-1"

PATCH = r'''

# ===== OPTION KING AI PATCH: MARKET-CLOSED CANDLE GUARD =====
# Version: 2026.05.09-market-closed-candle-guard-1

_OKAI_ORIGINAL_GET_CANDLES = get_candles
_okai_last_candle_skip_log = 0


def _okai_market_fetch_allowed():
    try:
        now_dt = market_now()
        session_open, session_reason = get_market_session_status(now_dt)
        return session_open, session_reason
    except Exception:
        return True, "Market status unavailable"


def get_candles(*args, **kwargs):
    """Avoid Angel candle API spam when market is closed/weekend."""
    global _okai_last_candle_skip_log
    session_open, session_reason = _okai_market_fetch_allowed()
    if not session_open:
        now_ts = time.time()
        if now_ts - _okai_last_candle_skip_log > 300:
            _okai_last_candle_skip_log = now_ts
            gui_log(f"Candle fetch skipped: {session_reason}")
        return None
    try:
        return _OKAI_ORIGINAL_GET_CANDLES(*args, **kwargs)
    except Exception as exc:
        text = str(exc)
        if "Couldn't parse the JSON response" in text and "b''" in text:
            now_ts = time.time()
            if now_ts - _okai_last_candle_skip_log > 60:
                _okai_last_candle_skip_log = now_ts
                gui_log("Candle fetch skipped: Angel returned empty response")
            return None
        raise

# ===== END PATCH =====
'''


def main():
    if not os.path.exists(APP_PATH):
        raise SystemExit("app.py not found. Run from /sdcard/Download/cloud_bot")

    text = open(APP_PATH, "r", encoding="utf-8").read()
    if VERSION in text:
        print("Patch already applied:", VERSION)
        return

    backup = f"app.py.bak_candle_guard_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    with open(backup, "w", encoding="utf-8") as file:
        file.write(text)

    text = re.sub(
        r'SERVER_VERSION\s*=\s*"[^"]+"',
        f'SERVER_VERSION = "{VERSION}"',
        text,
        count=1,
    )

    marker = '\nif __name__ == "__main__":'
    if marker not in text:
        raise SystemExit('Could not find main marker in app.py')

    text = text.replace(marker, PATCH + marker, 1)

    with open(APP_PATH, "w", encoding="utf-8") as file:
        file.write(text)

    import py_compile
    py_compile.compile(APP_PATH, doraise=True)
    print("Patch applied OK:", VERSION)
    print("Backup:", backup)
    print("Now restart server: bash ./termux_start.sh")


if __name__ == "__main__":
    main()
