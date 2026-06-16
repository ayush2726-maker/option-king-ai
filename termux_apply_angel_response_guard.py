import re
import shutil
import time

APP_PATH = "app.py"
NEW_VERSION = "2026.05.12-angel-response-guard-1"


def replace_block(text, start_marker, end_marker, new_block, label):
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"Start marker not found: {label}")
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(f"End marker not found: {label}")
    return text[:start] + new_block + text[end:]


with open(APP_PATH, "r", encoding="utf-8") as file:
    source = file.read()

backup = f"app.py.bak_angel_guard_{time.strftime('%Y%m%d_%H%M%S')}"
shutil.copy2(APP_PATH, backup)

source = re.sub(
    r'SERVER_VERSION = "[^"]+"',
    f'SERVER_VERSION = "{NEW_VERSION}"',
    source,
    count=1,
)

new_get_ltp = '''def get_ltp(exchange, symbol, token):
    angel_login()
    for attempt in range(5):
        try:
            data = obj.ltpData(exchange, symbol, token)
            if not isinstance(data, dict):
                raise RuntimeError(f"Invalid LTP response type {type(data).__name__}: {str(data)[:120]}")
            payload = data.get("data")
            if not isinstance(payload, dict):
                raise RuntimeError(f"Invalid LTP payload: {str(data)[:160]}")
            ltp = payload.get("ltp")
            if ltp is None:
                raise RuntimeError(f"LTP missing: {str(data)[:160]}")
            return float(ltp)
        except Exception as exc:
            gui_log(f"LTP retry {attempt + 1}/5: {exc}")
            time.sleep(2)
    return None


'''

source = replace_block(
    source,
    "def get_ltp(exchange, symbol, token):\n",
    "def get_nifty_price():\n",
    new_get_ltp,
    "get_ltp",
)

new_get_candles = '''def get_candles():
    global last_candle_df, last_candle_fetch_time, candle_rate_limited_until
    now_ts = time.time()
    if last_candle_df is not None and now_ts - last_candle_fetch_time < CANDLE_CACHE_SECONDS:
        return last_candle_df.copy()
    if candle_rate_limited_until > now_ts and last_candle_df is not None:
        return last_candle_df.copy()
    try:
        angel_login()
        data = obj.getCandleData({
            "exchange": "NSE",
            "symboltoken": NIFTY_TOKEN,
            "interval": "ONE_MINUTE",
            "fromdate": market_now().strftime("%Y-%m-%d 09:15"),
            "todate": market_now().strftime("%Y-%m-%d %H:%M"),
        })
        if not isinstance(data, dict):
            raise RuntimeError(f"Invalid candle response type {type(data).__name__}: {str(data)[:160]}")
        if data.get("status") is False:
            raise RuntimeError(str(data)[:240])
        rows = data.get("data", [])
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            raise RuntimeError(f"Invalid candle payload type {type(rows).__name__}: {str(rows)[:160]}")
        if rows and not isinstance(rows[0], (list, tuple)):
            raise RuntimeError(f"Invalid candle row: {str(rows[0])[:160]}")
        df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
        if df.empty:
            return last_candle_df.copy() if last_candle_df is not None else None
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna()
        if df.empty:
            return last_candle_df.copy() if last_candle_df is not None else None
        last_candle_df = df
        last_candle_fetch_time = now_ts
        return df.copy()
    except Exception as exc:
        msg = str(exc)
        lower = msg.lower()
        if "access rate" in lower or "access denied" in lower or "too many" in lower:
            candle_rate_limited_until = now_ts + CANDLE_RATE_LIMIT_COOLDOWN
        gui_log(f"Candle data wait: {msg[:180]}")
        return last_candle_df.copy() if last_candle_df is not None else None


'''

source = replace_block(
    source,
    "def get_candles():\n",
    "def get_indicators():\n",
    new_get_candles,
    "get_candles",
)

with open(APP_PATH, "w", encoding="utf-8") as file:
    file.write(source)

print(f"PATCH_OK {NEW_VERSION} backup={backup}")
