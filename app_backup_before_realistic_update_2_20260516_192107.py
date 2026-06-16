import csv
import datetime as dt
import hashlib
import json
import math
import numbers
import os
import py_compile
import shutil
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import pyotp
import requests
from SmartApi import SmartConnect


APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
CACHE_DIR = os.path.join(DATA_DIR, "angel_cache")
TRADE_DIR = os.path.join(DATA_DIR, "trade_data")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
MASTER_CACHE_PATH = os.path.join(CACHE_DIR, "OpenAPIScripMaster.json")

SERVER_VERSION = "2026.05.16-live-backtest-capital-1"
MOBILE_APP_VERSION = "1.0.0-build11"
DEFAULT_MOBILE_APP_UPDATE_URL = "https://expo.dev/accounts/ayush2726/projects/option-king-ai-mobile"
DEFAULT_UPDATE_MANIFEST_URLS = []
AUTO_UPDATE_INTERVAL_SECONDS = 300

NIFTY_SYMBOL = "Nifty 50"
NIFTY_TOKEN = "99926000"
NIFTY_TOKEN_FALLBACK = "26000"

ANALYSIS_START = dt.time(9, 15)
TRADE_START = dt.time(9, 25)
TRADE_END = dt.time(15, 15)
EXPIRY_TRADE_END = dt.time(15, 0)
ENTRY_CUTOFF_BUFFER_MINUTES = 30
EOD_EXIT_BUFFER_MINUTES = 5

FULL_SCORE_REQUIRED = 5
HALF_SCORE_REQUIRED = 4
GAP_FULL_SCORE_REQUIRED = 5
GAP_HALF_SCORE_REQUIRED = 4
HALF_TRADE_QTY_PERCENT = 50
FAST_LOT_SIZE = 65

SL_PERCENT = 12
TARGET_PERCENT = 24
EXPIRY_DAY_MODE = True
EXPIRY_SL_PERCENT = 12
EXPIRY_TARGET_PERCENT = 24
EXPIRY_TRAIL_GAP = 3
ORB_START = dt.time(9, 15)
ORB_END = dt.time(9, 20)
ORB_BREAK_BUFFER_POINTS = 5
GAP_DAY_THRESHOLD_POINTS = 80
MIN_CANDLE_BODY_RATIO = 0.30
MIN_EMA_GAP_POINTS = 3
MIN_VWAP_DISTANCE_POINTS = 4
MAX_ENTRY_EXTENSION_ATR = 1.20
MAX_VWAP_EXTENSION_ATR = 2.00
MAX_SAME_DIRECTION_RUN = 2
RECENT_EXTREME_LOOKBACK = 30
USE_SUPERTREND_FILTER = True
SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3.0
MARKET_HOLIDAYS = []
AUTO_START_BOT = True
MARKET_TIMEZONE = "Asia/Kolkata"
auto_start_done_for_day = None
READINESS_ALERT_TIME = dt.time(9, 0)
MORNING_WATCHDOG_READY_TIME = dt.time(9, 10)
MORNING_WATCHDOG_START_CHECK_TIME = dt.time(9, 16)
MORNING_WATCHDOG_FINAL_CHECK_TIME = dt.time(9, 20)
MORNING_WATCHDOG_END_TIME = dt.time(9, 35)
EOD_REPORT_TIME = dt.time(15, 35)
readiness_alert_done_for_day = None
morning_watchdog_ready_done_for_day = None
morning_watchdog_start_done_for_day = None
morning_watchdog_final_done_for_day = None
eod_report_done_for_day = None
DYNAMIC_TARGET_BOOST_PERCENT = 5
TARGET_EXTENSION_MAX_COUNT = 3
REENTRY_BLOCK_MINUTES = 20
REENTRY_BLOCK_REASONS = ("SL", "REVERSAL", "LOSS")
POST_EXIT_WAIT_MINUTES = 5
REVERSAL_MIN_HOLD_SECONDS = 300
REVERSAL_CONFIRM_CANDLES = 3
REVERSAL_MIN_LOSS_PERCENT = 6

MAX_DAILY_LOSS = 0.20
MAX_DAILY_TARGET = 0.50
DAILY_PROFIT_LOCK_LEVELS = (0.20, 0.30, 0.40, 0.50)
MAX_LOSS_STREAK = 2
MIN_PREMIUM = 30
MAX_RISK_PER_TRADE_PERCENT = 8.0
EARLY_PREMIUM_FAIL_EXIT_PERCENT = 8.0
EARLY_PREMIUM_FAIL_AFTER_SECONDS = 90
STOP_AND_REVERSE_ENABLED = True
STOP_AND_REVERSE_MIN_SCORE = 4
STOP_AND_REVERSE_TRADE_TYPE = "HALF"
STOP_AND_REVERSE_COOLDOWN_MINUTES = 15
EXTRA_CAPITAL_ALERT_LIMIT = 2000
CHARGES_ENABLED = True
BROKERAGE_PER_ORDER = 20.0
OPTION_TRANSACTION_RATE_NSE = 0.0003552
OPTION_TRANSACTION_RATE_BSE = 0.000325
OPTION_STT_SELL_RATE = 0.0015
OPTION_STAMP_BUY_RATE = 0.00003
SEBI_CHARGE_RATE = 10 / 10000000
IPFT_CHARGE_RATE = 0.000000001
GST_RATE = 0.18

config = {}
obj = None
master_cache = None
server = None
bot_thread = None
bot_running_lock = False
running = False

capital = 50000.0
paper_capital = 50000.0
daily_pnl = 0.0
daily_profit_floor = None
daily_profit_lock_level = 0.0
daily_target_alert_done = False

position = None
trade_history = []
trades_taken = 0
total_trades = 0
winning_trades = 0
losing_trades = 0
loss_streak = 0

last_confidence = 0
last_score = 0
last_signal = "WAIT"
last_trend = "--"
last_supertrend = "--"
last_nifty_price = None
last_market_scan = {"status": "Not run yet", "summary": "Market scan: --", "results": [], "timestamp": "--"}
last_trade_suggestion = {
    "action": "WAIT",
    "summary": "Suggestion: wait for setup",
    "signal": "WAIT",
    "trade_type": "NONE",
    "score": 0,
    "confidence": 0,
    "reason": "No setup checked yet",
    "timestamp": "--",
}
last_option_selection_reason = "Option selection not checked yet"
blocked_option_until = {}
blocked_strike_until = {}
blocked_direction_until = {}
post_exit_wait_until = 0
reverse_entry_block_until = 0
last_reverse_trade_ts = 0
last_backtest_report = "Mobile backtest not run yet."
last_backtest_summary = "Backtest: ready"
backtest_running = False
backtest_lock = threading.Lock()
last_health_summary = "Health: not checked"
last_update_status = {
    "status": "not_checked",
    "summary": "Auto update not checked yet",
    "timestamp": "--",
    "version": SERVER_VERSION,
}
logs = []
last_status_chart = None

orb_high = None
orb_low = None
orb_set = False
gap_day_mode = None
gap_day_direction = "UNKNOWN"
gap_day_points = 0.0
gap_day_checked_for = None
previous_close_cache = {}
last_candle_df = None
last_candle_fetch_time = 0
candle_rate_limited_until = 0
CANDLE_CACHE_SECONDS = 20
CANDLE_RATE_LIMIT_COOLDOWN = 180


def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(TRADE_DIR, exist_ok=True)


def load_config():
    global config, capital, paper_capital, MARKET_HOLIDAYS, AUTO_START_BOT, MARKET_TIMEZONE
    ensure_dirs()
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as file:
            config = json.load(file)
    else:
        config = {}
    capital = float(config.get("capital", capital))
    paper_capital = capital
    MARKET_HOLIDAYS = [str(day).strip() for day in config.get("market_holidays", []) if str(day).strip()]
    AUTO_START_BOT = bool(config.get("auto_start_bot", AUTO_START_BOT))
    MARKET_TIMEZONE = str(config.get("market_timezone", MARKET_TIMEZONE) or MARKET_TIMEZONE)


def api_token():
    return config.get("api_auth_token", "optionking-local")


def market_now():
    try:
        return dt.datetime.now(ZoneInfo(MARKET_TIMEZONE)).replace(tzinfo=None)
    except Exception:
        return dt.datetime.now()


def gui_log(text):
    timestamp = market_now().strftime("%H:%M:%S")
    line = f"{timestamp} | {text}"
    print(line, flush=True)
    logs.append(line)
    del logs[:-200]


def _send_msg_sync(msg):
    token = config.get("telegram_token", "")
    chat_id = config.get("chat_id", "")
    if not token or not chat_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        response = requests.get(url, params={"chat_id": chat_id, "text": msg}, timeout=5)
        if not response.ok:
            gui_log(f"Telegram send failed: HTTP {response.status_code}")
            return False
        return True
    except Exception as exc:
        gui_log(f"Telegram send error: {exc}")
        return False


def send_msg(msg, wait=False):
    """Send Telegram alerts without blocking live status/API responses."""
    if wait:
        return _send_msg_sync(msg)
    token = config.get("telegram_token", "")
    chat_id = config.get("chat_id", "")
    if not token or not chat_id:
        return False
    threading.Thread(target=_send_msg_sync, args=(msg,), daemon=True).start()
    return True


def save_cloud_config():
    ensure_dirs()
    with open(CONFIG_PATH, "w", encoding="utf-8") as file:
        json.dump(config, file, indent=2)


def update_telegram_config(token, chat_id):
    token = str(token or "").strip()
    chat_id = str(chat_id or "").strip()
    if not token or not chat_id:
        raise RuntimeError("Telegram token/chat_id missing")
    config["telegram_token"] = token
    config["chat_id"] = chat_id
    save_cloud_config()
    gui_log("Telegram settings saved on phone server")


def mobile_app_update_payload():
    return {
        "app": "Option King AI Mobile",
        "latest_version": config.get("mobile_app_version", MOBILE_APP_VERSION),
        "current_server_version": SERVER_VERSION,
        "apk_url": config.get("mobile_app_update_url", DEFAULT_MOBILE_APP_UPDATE_URL),
        "release_notes": config.get(
            "mobile_app_release_notes",
                "Strategy updated: capital 50000, profit lock ladder 20/30/40/50%, and strict gap reversal filters.",
        ),
        "updated_at": config.get("mobile_app_updated_at", "--"),
    }


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def update_manifest_urls():
    urls = config.get("update_manifest_urls", DEFAULT_UPDATE_MANIFEST_URLS)
    if isinstance(urls, str):
        urls = [item.strip() for item in urls.split(",")]
    cleaned = []
    for url in urls or []:
        url = str(url or "").strip()
        if url and url not in cleaned:
            cleaned.append(url)
    return cleaned


def set_update_status(status, summary, **extra):
    global last_update_status
    payload = {
        "status": status,
        "summary": summary,
        "timestamp": market_now().isoformat(timespec="seconds"),
        "version": SERVER_VERSION,
    }
    payload.update(extra)
    last_update_status = payload
    return payload


def fetch_json(url, timeout=15):
    request = urllib.request.Request(url, headers={"User-Agent": "OptionKingAI-PhoneServer"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_bytes(url, timeout=30):
    request = urllib.request.Request(url, headers={"User-Agent": "OptionKingAI-PhoneServer"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def manifest_app_url(manifest_url, manifest):
    explicit = str(manifest.get("app_url") or "").strip()
    if explicit:
        return explicit
    app_path = str(manifest.get("app_path") or "app.py").lstrip("/")
    base = manifest_url.rsplit("/", 1)[0]
    return f"{base}/{app_path}"


def restart_process_soon(reason):
    def _restart():
        time.sleep(2)
        gui_log(f"Restarting phone server: {reason}")
        os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)])

    threading.Thread(target=_restart, daemon=True).start()


def check_server_update(force=False, source="auto"):
    if not bool(config.get("auto_update_enabled", False)):
        return set_update_status(
            "disabled",
            "Auto update disabled. Use direct SSH/manual update when needed.",
            source=source,
        )

    manifest_urls = update_manifest_urls()
    if not manifest_urls:
        return set_update_status(
            "disabled",
            "Auto update source not configured. No update check needed.",
            source=source,
        )

    current_path = os.path.abspath(__file__)
    current_hash = file_sha256(current_path)

    if not force and (running or position is not None):
        return set_update_status(
            "deferred",
            "Update available check deferred while bot is running or position is open",
            running=running,
            position_open=position is not None,
            source=source,
        )

    errors = []
    for manifest_url in manifest_urls:
        temp_path = ""
        try:
            manifest = fetch_json(manifest_url)
            remote_hash = str(manifest.get("sha256") or "").strip().lower()
            if not remote_hash:
                raise RuntimeError("manifest missing sha256")

            remote_version = str(manifest.get("version") or "unknown")
            if remote_hash == current_hash:
                return set_update_status(
                    "up_to_date",
                    f"Phone server already up to date ({remote_version})",
                    remote_version=remote_version,
                    manifest_url=manifest_url,
                    source=source,
                )

            app_url = manifest_app_url(manifest_url, manifest)
            data = fetch_bytes(app_url)
            expected_size = int(manifest.get("size") or 0)
            if expected_size and len(data) != expected_size:
                raise RuntimeError(f"size mismatch: got {len(data)}, expected {expected_size}")
            downloaded_hash = hashlib.sha256(data).hexdigest()
            if downloaded_hash.lower() != remote_hash:
                raise RuntimeError("sha256 mismatch after download")

            fd, temp_path = tempfile.mkstemp(prefix="app_update_", suffix=".py", dir=APP_DIR)
            with os.fdopen(fd, "wb") as file:
                file.write(data)
            py_compile.compile(temp_path, doraise=True)

            backup_path = os.path.join(APP_DIR, f"app.py.bak_{market_now().strftime('%Y%m%d_%H%M%S')}")
            shutil.copy2(current_path, backup_path)
            os.replace(temp_path, current_path)
            temp_path = ""

            result = set_update_status(
                "updated",
                f"Phone server updated to {remote_version}; restarting",
                remote_version=remote_version,
                manifest_url=manifest_url,
                backup_path=backup_path,
                source=source,
            )
            gui_log(result["summary"])
            send_msg("Option King AI phone server updated. Restarting now.")
            restart_process_soon("auto update")
            return result
        except Exception as exc:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            errors.append(f"{manifest_url}: {exc}")

    summary = "No update manifest reachable"
    if errors:
        summary = "Auto update failed: " + " | ".join(errors[-2:])
    gui_log(summary)
    return set_update_status("error", summary, errors=errors, source=source)


def auto_update_loop():
    time.sleep(20)
    while True:
        try:
            if bool(config.get("auto_update_enabled", True)):
                check_server_update(force=False, source="auto")
        except Exception as exc:
            gui_log(f"Auto update loop error: {exc}")
            set_update_status("error", f"Auto update loop error: {exc}", source="auto")
        interval = int(config.get("auto_update_interval_seconds", AUTO_UPDATE_INTERVAL_SECONDS) or AUTO_UPDATE_INTERVAL_SECONDS)
        time.sleep(max(60, interval))


def angel_login():
    global obj
    if obj is not None:
        return
    required = ["api_key", "client_id", "password", "totp_secret"]
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise RuntimeError("Missing config: " + ", ".join(missing))
    for attempt in range(3):
        try:
            obj = SmartConnect(api_key=config["api_key"])
            totp = pyotp.TOTP(config["totp_secret"]).now()
            session = obj.generateSession(config["client_id"], config["password"], totp)
            if not session or session.get("status") is False:
                raise RuntimeError(f"Login failed: {session}")
            gui_log("Angel One login done")
            return
        except Exception as exc:
            obj = None
            gui_log(f"Login retry {attempt + 1}: {exc}")
            time.sleep(3)
    raise RuntimeError("Login failed after retries")


def get_ltp(exchange, symbol, token):
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


def get_nifty_price():
    price = get_ltp("NSE", NIFTY_SYMBOL, NIFTY_TOKEN)
    if price is None:
        price = get_ltp("NSE", "NIFTY", NIFTY_TOKEN_FALLBACK)
    return price


def get_candles():
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


def get_indicators():
    df = get_candles()
    if df is None or len(df) < 21:
        return None
    df = df.copy()
    df["EMA9"] = df["close"].ewm(span=9).mean()
    df["EMA21"] = df["close"].ewm(span=21).mean()
    df["VWAP"] = compute_vwap_or_session_average(df)
    df = add_supertrend(df)
    return df


def compute_vwap_or_session_average(df):
    """Use real VWAP when volume exists; NIFTY index often has zero volume, so use session average."""
    work = df.copy()
    for col in ["high", "low", "close"]:
        work[col] = pd.to_numeric(work[col], errors="coerce")
    volume = pd.to_numeric(work.get("volume", 0), errors="coerce").fillna(0)
    typical = ((work["high"] + work["low"] + work["close"]) / 3).fillna(work["close"])
    if float(volume.sum() or 0) > 0:
        volume_sum = volume.cumsum().replace(0, pd.NA)
        vwap = ((typical * volume).cumsum() / volume_sum).ffill()
        return vwap.fillna(typical.expanding().mean()).fillna(work["close"])
    return typical.expanding().mean().fillna(work["close"])


def add_supertrend(df, period=None, multiplier=None):
    period = int(config.get("supertrend_period", period or SUPERTREND_PERIOD) or SUPERTREND_PERIOD)
    multiplier = float(config.get("supertrend_multiplier", multiplier or SUPERTREND_MULTIPLIER) or SUPERTREND_MULTIPLIER)
    if df is None or df.empty:
        return df

    df = df.copy()
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    hl2 = (high + low) / 2
    basic_upper = hl2 + (multiplier * atr)
    basic_lower = hl2 - (multiplier * atr)

    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()
    direction = [None] * len(df)
    supertrend = [float("nan")] * len(df)

    for index in range(len(df)):
        if index == 0 or pd.isna(atr.iloc[index]):
            direction[index] = "NEUTRAL"
            continue

        prev_index = index - 1
        if not pd.isna(final_upper.iloc[prev_index]):
            if basic_upper.iloc[index] > final_upper.iloc[prev_index] and close.iloc[prev_index] <= final_upper.iloc[prev_index]:
                final_upper.iloc[index] = final_upper.iloc[prev_index]
        if not pd.isna(final_lower.iloc[prev_index]):
            if basic_lower.iloc[index] < final_lower.iloc[prev_index] and close.iloc[prev_index] >= final_lower.iloc[prev_index]:
                final_lower.iloc[index] = final_lower.iloc[prev_index]

        previous_direction = direction[prev_index] if direction[prev_index] in {"UP", "DOWN"} else "UP"
        if previous_direction == "DOWN" and close.iloc[index] > final_upper.iloc[index]:
            current_direction = "UP"
        elif previous_direction == "UP" and close.iloc[index] < final_lower.iloc[index]:
            current_direction = "DOWN"
        else:
            current_direction = previous_direction

        direction[index] = current_direction
        supertrend[index] = final_lower.iloc[index] if current_direction == "UP" else final_upper.iloc[index]

    df["ATR"] = atr
    df["SUPERTREND"] = supertrend
    df["SUPERTREND_DIR"] = direction
    return df


def candle_times(df):
    parsed = pd.to_datetime(df["time"], errors="coerce")
    try:
        if getattr(parsed.dt, "tz", None) is not None:
            parsed = parsed.dt.tz_convert(None)
    except Exception:
        try:
            parsed = parsed.dt.tz_localize(None)
        except Exception:
            pass
    return parsed


def gap_day_threshold_points():
    try:
        return max(0.0, float(config.get("gap_day_threshold_points", GAP_DAY_THRESHOLD_POINTS)))
    except Exception:
        return float(GAP_DAY_THRESHOLD_POINTS)


def previous_working_day(day):
    probe = day - dt.timedelta(days=1)
    while not is_market_working_day(probe):
        probe -= dt.timedelta(days=1)
    return probe


def fetch_previous_index_close(day=None):
    global previous_close_cache
    day = day or market_now().date()
    if isinstance(day, dt.datetime):
        day = day.date()
    prev_day = previous_working_day(day)
    cache_key_value = market_day_text(prev_day)
    if cache_key_value in previous_close_cache:
        return previous_close_cache[cache_key_value]

    from_day = prev_day - dt.timedelta(days=10)
    for token in (NIFTY_TOKEN, NIFTY_TOKEN_FALLBACK):
        try:
            angel_login()
            data = obj.getCandleData({
                "exchange": "NSE",
                "symboltoken": token,
                "interval": "ONE_DAY",
                "fromdate": f"{from_day.strftime('%Y-%m-%d')} 09:15",
                "todate": f"{prev_day.strftime('%Y-%m-%d')} 15:30",
            })
            if not data or data.get("status") is False:
                continue
            df = pd.DataFrame(data.get("data", []), columns=["time", "open", "high", "low", "close", "volume"])
            if df.empty:
                continue
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.dropna(subset=["close"])
            if df.empty:
                continue
            previous_close_cache[cache_key_value] = float(df.iloc[-1]["close"])
            return previous_close_cache[cache_key_value]
        except Exception as exc:
            gui_log(f"Previous close fetch error: {exc}")

    previous_close_cache[cache_key_value] = None
    return None


def update_gap_day_mode(df=None, force=False):
    global gap_day_mode, gap_day_direction, gap_day_points, gap_day_checked_for
    today = market_now().date()
    today_key = market_day_text(today)
    if not force and gap_day_checked_for == today_key and gap_day_mode is not None:
        return bool(gap_day_mode)

    if df is None:
        df = get_candles()
    if df is None or df.empty:
        gap_day_mode = False
        gap_day_direction = "UNKNOWN"
        gap_day_points = 0.0
        gap_day_checked_for = today_key
        return False

    work = df.copy()
    work["__dt"] = candle_times(work)
    opening = work[
        (work["__dt"].dt.time >= ORB_START)
        & (work["__dt"].dt.time < ORB_END)
    ].dropna(subset=["__dt"])
    first_row = opening.iloc[0] if not opening.empty else work.iloc[0]
    first_open = float(first_row["open"])
    prev_close = fetch_previous_index_close(today)
    if not prev_close:
        gap_day_mode = False
        gap_day_direction = "UNKNOWN"
        gap_day_points = 0.0
        gap_day_checked_for = today_key
        gui_log("Gap check skipped: previous close unavailable")
        return False

    gap_day_points = first_open - float(prev_close)
    threshold = gap_day_threshold_points()
    gap_day_mode = abs(gap_day_points) >= threshold
    gap_day_direction = "GAP UP" if gap_day_points > 0 else "GAP DOWN" if gap_day_points < 0 else "FLAT"
    gap_day_checked_for = today_key
    mode_text = "GAP DAY - ORB OFF" if gap_day_mode else "NORMAL DAY - ORB 4TH"
    gui_log(
        f"Gap check | Open {first_open:.2f} | Prev close {prev_close:.2f} | "
        f"Gap {gap_day_points:.2f} | {mode_text}"
    )
    return bool(gap_day_mode)


def gap_day_summary():
    if gap_day_mode is None:
        return "UNKNOWN"
    orb_text = "ORB OFF" if gap_day_mode else "ORB 4TH"
    return f"{gap_day_direction} {gap_day_points:.2f} | {orb_text}"


def backtest_gap_day_mode(df, day=None):
    if df is None or df.empty:
        return False
    if day is None:
        parsed = candle_times(df)
        first_valid = parsed.dropna()
        day = first_valid.iloc[0].date() if not first_valid.empty else market_now().date()
    prev_close = fetch_previous_index_close(day)
    if not prev_close:
        return False
    first_open = float(df.iloc[0]["open"])
    return abs(first_open - float(prev_close)) >= gap_day_threshold_points()


def backtest_gap_day_direction(df, day=None):
    if df is None or df.empty:
        return "UNKNOWN"
    if day is None:
        parsed = candle_times(df)
        first_valid = parsed.dropna()
        day = first_valid.iloc[0].date() if not first_valid.empty else market_now().date()
    prev_close = fetch_previous_index_close(day)
    if not prev_close:
        return "UNKNOWN"
    first_open = float(df.iloc[0]["open"])
    gap_points = first_open - float(prev_close)
    if abs(gap_points) < gap_day_threshold_points():
        return "FLAT"
    return "GAP UP" if gap_points > 0 else "GAP DOWN"


def set_orb():
    global orb_high, orb_low, orb_set
    df = get_candles()
    if df is None or len(df) < 5:
        gui_log("Waiting for ORB data")
        return
    df = df.copy()
    df["__dt"] = candle_times(df)
    opening = df[
        (df["__dt"].dt.time >= ORB_START)
        & (df["__dt"].dt.time < ORB_END)
    ].dropna(subset=["__dt"])
    if len(opening) < 3:
        if market_now().time() < ORB_END:
            gui_log("Waiting for opening ORB candles")
            return
        opening = df.head(5)
        gui_log("ORB time parse incomplete, using first 5 candles instead of latest candles")
    orb_high = float(opening["high"].max())
    orb_low = float(opening["low"].min())
    orb_set = True
    update_gap_day_mode(df)
    gui_log(f"Opening ORB set | {ORB_START.strftime('%H:%M')}-{ORB_END.strftime('%H:%M')} | High {orb_high:.2f} | Low {orb_low:.2f}")


def predict_trend():
    df = get_indicators()
    if df is None or len(df) < 20:
        return "NEUTRAL"
    last = df.iloc[-1]
    if last["EMA9"] > last["EMA21"]:
        return "UPTREND"
    if last["EMA9"] < last["EMA21"]:
        return "DOWNTREND"
    return "NEUTRAL"


def candle_body_ratio(candle):
    candle_range = float(candle["high"] - candle["low"])
    if candle_range <= 0:
        return 0
    return abs(float(candle["close"] - candle["open"])) / candle_range


def has_strong_two_candle_momentum(c1, c2, signal):
    if signal == "CE":
        same_direction = c1["close"] > c1["open"] and c2["close"] > c2["open"]
    else:
        same_direction = c1["close"] < c1["open"] and c2["close"] < c2["open"]
    if not same_direction:
        return False
    return candle_body_ratio(c1) >= MIN_CANDLE_BODY_RATIO and candle_body_ratio(c2) >= MIN_CANDLE_BODY_RATIO


def candle_momentum_reason(c1, c2, signal):
    direction = "green" if signal == "CE" else "red"
    c1_up = c1["close"] > c1["open"]
    c2_up = c2["close"] > c2["open"]
    c1_ok_dir = c1_up if signal == "CE" else not c1_up
    c2_ok_dir = c2_up if signal == "CE" else not c2_up
    c1_body = candle_body_ratio(c1) * 100
    c2_body = candle_body_ratio(c2) * 100
    notes = []
    if not c1_ok_dir or not c2_ok_dir:
        notes.append(f"need 2 {direction} closed candles")
    if c1_body < (MIN_CANDLE_BODY_RATIO * 100) or c2_body < (MIN_CANDLE_BODY_RATIO * 100):
        notes.append(f"body {c1_body:.0f}%/{c2_body:.0f}% < {MIN_CANDLE_BODY_RATIO * 100:.0f}%")
    return "; ".join(notes) or f"2 closed {direction} candles OK"


def recent_atr_points(df, period=14):
    if df is None or len(df) < 3:
        return 0.0
    work = df.tail(period + 1).copy()
    high = pd.to_numeric(work["high"], errors="coerce")
    low = pd.to_numeric(work["low"], errors="coerce")
    close = pd.to_numeric(work["close"], errors="coerce")
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    value = float(tr.dropna().tail(period).mean() or 0)
    return max(value, 1.0)


def same_direction_run_count(df, signal, lookback=6):
    if df is None or len(df) < 1:
        return 0
    run = 0
    for _, row in df.tail(lookback).iloc[::-1].iterrows():
        up = float(row["close"]) > float(row["open"])
        down = float(row["close"]) < float(row["open"])
        if signal == "CE" and up:
            run += 1
        elif signal == "PE" and down:
            run += 1
        else:
            break
    return run


def entry_timing_guard(df, signal, price, vwap, ema9):
    """Block chase entries that arrive after the move is already stretched."""
    if not signal or df is None or len(df) < 8:
        return True, ""

    closed = df.iloc[:-1].copy() if len(df) > 1 else df.copy()
    if len(closed) < 8:
        return True, ""

    atr = recent_atr_points(closed)
    try:
        max_ema_extension = max(18.0, atr * float(config.get("max_entry_extension_atr", MAX_ENTRY_EXTENSION_ATR)))
        max_vwap_extension = max(35.0, atr * float(config.get("max_vwap_extension_atr", MAX_VWAP_EXTENSION_ATR)))
        max_run = max(1, int(config.get("max_same_direction_run", MAX_SAME_DIRECTION_RUN)))
        extreme_lookback = max(10, int(config.get("recent_extreme_lookback", RECENT_EXTREME_LOOKBACK)))
    except Exception:
        max_ema_extension = max(18.0, atr * MAX_ENTRY_EXTENSION_ATR)
        max_vwap_extension = max(35.0, atr * MAX_VWAP_EXTENSION_ATR)
        max_run = MAX_SAME_DIRECTION_RUN
        extreme_lookback = RECENT_EXTREME_LOOKBACK

    price = float(price)
    vwap = float(vwap)
    ema9 = float(ema9)
    run = same_direction_run_count(closed, signal)
    recent = closed.tail(extreme_lookback)
    last = closed.iloc[-1]

    if signal == "CE":
        ema_extension = price - ema9
        vwap_extension = price - vwap
        recent_high = float(recent["high"].max())
        if ema_extension > max_ema_extension:
            return False, f"Timing blocked CE: price stretched {ema_extension:.1f} pts above EMA9; wait pullback/retest"
        if vwap_extension > max_vwap_extension:
            return False, f"Timing blocked CE: price stretched {vwap_extension:.1f} pts above VWAP/session average"
        if run > max_run and price >= recent_high - (atr * 0.25):
            return False, f"Timing blocked CE: chasing {run} green candles near recent high {recent_high:.1f}"
        if float(last["close"]) < float(last["high"]) - (atr * 0.55):
            return False, "Timing blocked CE: last candle rejected from high"

    if signal == "PE":
        ema_extension = ema9 - price
        vwap_extension = vwap - price
        recent_low = float(recent["low"].min())
        if ema_extension > max_ema_extension:
            return False, f"Timing blocked PE: price stretched {ema_extension:.1f} pts below EMA9; wait pullback/retest"
        if vwap_extension > max_vwap_extension:
            return False, f"Timing blocked PE: price stretched {vwap_extension:.1f} pts below VWAP/session average"
        if run > max_run and price <= recent_low + (atr * 0.25):
            return False, f"Timing blocked PE: chasing {run} red candles near recent low {recent_low:.1f}"
        if float(last["close"]) > float(last["low"]) + (atr * 0.55):
            return False, "Timing blocked PE: last candle rejected from low"

    return True, ""


def supertrend_filter_enabled():
    return bool(config.get("use_supertrend_filter", USE_SUPERTREND_FILTER))


def reentry_block_minutes():
    try:
        return max(1.0, float(config.get("reentry_block_minutes", REENTRY_BLOCK_MINUTES)))
    except Exception:
        return float(REENTRY_BLOCK_MINUTES)


def post_exit_wait_minutes():
    try:
        return max(0.0, float(config.get("post_exit_wait_minutes", POST_EXIT_WAIT_MINUTES)))
    except Exception:
        return float(POST_EXIT_WAIT_MINUTES)


def normalize_trade_type(trade_type, allow_none=False):
    trade_type = str(trade_type or "").strip().upper()
    if trade_type in {"FULL", "HALF"}:
        return trade_type
    if allow_none and trade_type == "NONE":
        return "NONE"
    return "FULL"


def trade_score_requirements(gap_day=False):
    if gap_day:
        return int(GAP_FULL_SCORE_REQUIRED), int(GAP_HALF_SCORE_REQUIRED)
    return int(FULL_SCORE_REQUIRED), int(HALF_SCORE_REQUIRED)


def profit_lock_levels():
    max_level = float(MAX_DAILY_TARGET or 0)
    levels = [float(level) for level in DAILY_PROFIT_LOCK_LEVELS if 0 < float(level) <= max_level]
    if max_level > 0 and all(abs(level - max_level) > 0.0001 for level in levels):
        levels.append(max_level)
    return tuple(sorted(set(levels)))


def profit_lock_levels_text():
    return " / ".join(f"{level * 100:.0f}%" for level in profit_lock_levels())


def update_profit_lock_floor(live_equity):
    global daily_profit_floor, daily_profit_lock_level, daily_target_alert_done
    changed = False
    for level in profit_lock_levels():
        if live_equity >= paper_capital * (1 + level) and level > float(daily_profit_lock_level or 0):
            daily_profit_lock_level = level
            daily_profit_floor = paper_capital * (1 + level)
            daily_target_alert_done = True
            changed = True
            gui_log(f"Daily profit lock {level * 100:.0f}% achieved. Floor locked at {daily_profit_floor:.2f}.")
    return changed


def backtest_profit_lock_update(start_capital, live_equity, lock_level, profit_floor):
    changed = False
    for level in profit_lock_levels():
        if live_equity >= start_capital * (1 + level) and level > float(lock_level or 0):
            lock_level = level
            profit_floor = start_capital * (1 + level)
            changed = True
    return lock_level, profit_floor, changed


def half_trade_qty_percent():
    try:
        value = float(config.get("half_trade_qty_percent", HALF_TRADE_QTY_PERCENT))
    except Exception:
        value = float(HALF_TRADE_QTY_PERCENT)
    return min(100.0, max(1.0, value))


def qty_lots_for_trade_type(max_lots, trade_type="FULL"):
    max_lots = int(max_lots or 0)
    if max_lots <= 0:
        return 0
    if normalize_trade_type(trade_type) == "HALF":
        return max(1, min(max_lots, int(math.floor(max_lots * (half_trade_qty_percent() / 100)))))
    return max_lots


def clean_reentry_blocks():
    global post_exit_wait_until
    now_ts = time.time()
    if float(post_exit_wait_until or 0) <= now_ts:
        post_exit_wait_until = 0
    for store in (blocked_option_until, blocked_strike_until, blocked_direction_until):
        for key, until_ts in list(store.items()):
            if float(until_ts or 0) <= now_ts:
                store.pop(key, None)


def strike_block_key(signal, option):
    if not option:
        return ""
    strike = option.get("strike")
    if strike in (None, ""):
        return ""
    try:
        strike = int(float(strike))
    except Exception:
        strike = str(strike)
    return f"{signal}:{strike}"


def block_remaining_text(until_ts):
    seconds = max(0, int(float(until_ts or 0) - time.time()))
    minutes = max(1, math.ceil(seconds / 60))
    return f"{minutes}m"


def option_reentry_block_reason(signal, option):
    clean_reentry_blocks()
    symbol = str((option or {}).get("symbol") or "")
    if symbol and blocked_option_until.get(symbol, 0) > time.time():
        return f"same option cooldown {block_remaining_text(blocked_option_until[symbol])}"
    key = strike_block_key(signal, option)
    if key and blocked_strike_until.get(key, 0) > time.time():
        return f"same strike cooldown {block_remaining_text(blocked_strike_until[key])}"
    return ""


def direction_reentry_block_reason(signal):
    clean_reentry_blocks()
    signal = str(signal or "")
    if signal and blocked_direction_until.get(signal, 0) > time.time():
        return f"{signal} direction cooldown {block_remaining_text(blocked_direction_until[signal])}"
    return ""


def post_exit_wait_reason():
    clean_reentry_blocks()
    if float(post_exit_wait_until or 0) > time.time():
        return f"post-exit wait {block_remaining_text(post_exit_wait_until)}"
    return ""


def reentry_blocks_summary():
    clean_reentry_blocks()
    blocks = []
    if float(post_exit_wait_until or 0) > time.time():
        blocks.append(f"wait {block_remaining_text(post_exit_wait_until)}")
    for signal, until_ts in sorted(blocked_direction_until.items()):
        blocks.append(f"{signal} direction {block_remaining_text(until_ts)}")
    for symbol, until_ts in sorted(blocked_option_until.items()):
        blocks.append(f"{symbol} {block_remaining_text(until_ts)}")
    for key, until_ts in sorted(blocked_strike_until.items()):
        blocks.append(f"{key} {block_remaining_text(until_ts)}")
    return ", ".join(blocks[:5]) if blocks else "OFF"


def register_reentry_block(reason, net_pnl):
    global post_exit_wait_until
    if position is None:
        return
    reason_text = str(reason or "").upper()
    wait_minutes = post_exit_wait_minutes()
    if wait_minutes > 0:
        post_exit_wait_until = max(post_exit_wait_until, time.time() + (wait_minutes * 60))
    should_block = float(net_pnl or 0) < 0 or any(text in reason_text for text in REENTRY_BLOCK_REASONS)
    if not should_block:
        if wait_minutes > 0:
            gui_log(f"New trade wait {wait_minutes:.0f}m after exit | Reason: {reason}")
        return
    option = position.get("option") or {}
    signal = position.get("signal", "")
    until_ts = time.time() + (reentry_block_minutes() * 60)
    symbol = str(option.get("symbol") or "")
    if signal:
        blocked_direction_until[str(signal)] = until_ts
    if symbol:
        blocked_option_until[symbol] = until_ts
    key = strike_block_key(signal, option)
    if key:
        blocked_strike_until[key] = until_ts
    wait_text = f" | New trade wait {wait_minutes:.0f}m" if wait_minutes > 0 else ""
    gui_log(f"Re-entry blocked for {reentry_block_minutes():.0f}m | Direction {signal} | {symbol or key or signal} | Reason: {reason}{wait_text}")


def choose_rule_signal(price, vwap, ema9, ema21, trend, supertrend_dir, c1, c2, ce_score, pe_score):
    gap_day = bool(gap_day_mode)
    has_orb = orb_high is not None and orb_low is not None
    orb_required = (not gap_day) and has_orb
    ce_breakout = has_orb and price > (orb_high + ORB_BREAK_BUFFER_POINTS) and c2["close"] > orb_high
    pe_breakout = has_orb and price < (orb_low - ORB_BREAK_BUFFER_POINTS) and c2["close"] < orb_low
    ce_orb_ok = (not gap_day) and has_orb and ce_breakout
    pe_orb_ok = (not gap_day) and has_orb and pe_breakout
    ce_vwap = price > vwap
    pe_vwap = price < vwap
    ce_supertrend = (supertrend_dir == "UP") or not supertrend_filter_enabled()
    pe_supertrend = (supertrend_dir == "DOWN") or not supertrend_filter_enabled()
    ce_trend = ema9 > ema21 and trend == "UPTREND"
    pe_trend = ema9 < ema21 and trend == "DOWNTREND"
    ema_gap = abs(ema9 - ema21)
    vwap_distance = abs(price - vwap)
    choppy_warning = ema_gap < MIN_EMA_GAP_POINTS and vwap_distance < MIN_VWAP_DISTANCE_POINTS
    if choppy_warning and max(ce_score, pe_score) < 4:
        return None, "NONE", 0, "Choppy market: EMA/VWAP too close"

    ce_momentum = has_strong_two_candle_momentum(c1, c2, "CE")
    pe_momentum = has_strong_two_candle_momentum(c1, c2, "PE")
    raw_gap_up_pe_sustain = (
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
    ce_full_continuation = (
        (not gap_day)
        and ce_orb_ok
        and float(c2.get("close", price)) > float(c1.get("high", price))
        and float(price) > float(c2.get("high", price))
        and not choppy_warning
    )
    pe_full_continuation = (
        (not gap_day)
        and pe_orb_ok
        and float(c2.get("close", price)) < float(c1.get("low", price))
        and float(price) < float(c2.get("low", price))
        and not choppy_warning
    )
    # FULL is now only a confirmed continuation trade. Gap days stay HALF/risk-capped.
    ce_full_core = ce_half_core and ce_full_continuation
    pe_full_core = pe_half_core and pe_full_continuation

    wait_reason = post_exit_wait_reason()
    if wait_reason:
        return None, "NONE", 0, "Post-exit wait active: " + wait_reason

    gap_text = " | Gap day ORB OFF" if gap_day else ""

    def build_candidate(signal, score, half_ok, full_ok, vwap_ok, supertrend_ok, orb_ok, trend_ok, momentum_ok, gap_filter_ok=True, gap_filter_label="GAP FILTER"):
        if not half_ok:
            missing = []
            if not vwap_ok:
                missing.append("VWAP")
            if not supertrend_ok:
                missing.append("SUPERTREND")
            if not momentum_ok:
                missing.append(f"CANDLE ({candle_momentum_reason(c1, c2, signal)})")
            if not trend_ok:
                missing.append("EMA")
            if not gap_filter_ok:
                missing.append(gap_filter_label)
            return None, f"{signal} blocked: HALF core missing {', '.join(missing)}{gap_text}"

        block_reason = direction_reentry_block_reason(signal)
        if full_ok:
            trade_type = "FULL"
            confidence = 92
            if gap_day:
                reason = f"Full {signal}: VWAP + Supertrend + candle momentum + EMA | Gap day ORB OFF; using FULL amount"
            else:
                reason = f"Full {signal}: VWAP + Supertrend + candle momentum + EMA, plus ORB"
            full_rank = 2
            if block_reason:
                reason += " | same-direction cooldown overridden by FULL setup"
        else:
            if block_reason:
                return None, f"{signal} blocked: {block_reason}"
            trade_type = "HALF"
            confidence = 74
            full_rank = 1
            pending = []
            if (not gap_day) and not orb_ok:
                pending.append("ORB")
            if (not gap_day) and orb_ok and not (ce_full_continuation if signal == "CE" else pe_full_continuation):
                pending.append("continuation")
            reason = f"Half {signal}: VWAP + Supertrend + candle momentum + EMA"
            if pending:
                reason += " | FULL pending: " + " + ".join(pending)
            elif gap_day:
                reason += " | Gap day ORB OFF; FULL disabled"
            if gap_day and signal == "CE" and gap_day_direction == "GAP DOWN" and not raw_gap_down_ce_sustain:
                reason += " | GAP-DOWN CE sustain relaxed"
            if gap_day and signal == "PE" and gap_day_direction == "GAP UP" and not raw_gap_up_pe_sustain:
                reason += " | GAP-UP PE sustain relaxed"
            if choppy_warning:
                reason += " | Choppy warning ignored because score is 4/5+"

        return {
            "signal": signal,
            "trade_type": trade_type,
            "confidence": confidence,
            "score": score,
            "reason": reason,
            "full_rank": full_rank,
        }, ""

    candidates = []
    blocked_reasons = []
    ce_candidate, ce_blocked = build_candidate(
        "CE", ce_score, ce_half_core, ce_full_core, ce_vwap, ce_supertrend, ce_orb_ok, ce_trend, ce_momentum, gap_down_ce_sustain, "GAP-DOWN CE SUSTAIN"
    )
    pe_candidate, pe_blocked = build_candidate(
        "PE", pe_score, pe_half_core, pe_full_core, pe_vwap, pe_supertrend, pe_orb_ok, pe_trend, pe_momentum, gap_up_pe_sustain, "GAP-UP PE SUSTAIN"
    )
    if ce_candidate:
        candidates.append(ce_candidate)
    elif ce_score >= 3:
        blocked_reasons.append((ce_score, ce_blocked))
    if pe_candidate:
        candidates.append(pe_candidate)
    elif pe_score >= 3:
        blocked_reasons.append((pe_score, pe_blocked))

    if candidates:
        candidates.sort(key=lambda item: (item["full_rank"], item["score"], item["confidence"]), reverse=True)
        best = candidates[0]
        return best["signal"], best["trade_type"], best["confidence"], best["reason"]

    if blocked_reasons:
        blocked_reasons.sort(key=lambda item: item[0], reverse=True)
        return None, "NONE", 0, blocked_reasons[0][1]

    if max(ce_score, pe_score) >= 3:
        return None, "NONE", 0, "Setup blocked: no clear CE/PE core edge"
    return None, "NONE", 0, "No setup"


def market_day_text(date_value=None):
    date_value = date_value or market_now().date()
    if isinstance(date_value, dt.datetime):
        date_value = date_value.date()
    return date_value.strftime("%Y-%m-%d")


def is_market_working_day(date_value=None):
    date_value = date_value or market_now().date()
    if isinstance(date_value, dt.datetime):
        date_value = date_value.date()
    return date_value.weekday() < 5 and market_day_text(date_value) not in set(MARKET_HOLIDAYS)


def is_expiry_day(date_value=None):
    date_value = date_value or market_now().date()
    if isinstance(date_value, dt.datetime):
        date_value = date_value.date()

    override = config.get("expiry_day_mode")
    if isinstance(override, bool):
        return override
    if isinstance(override, str):
        text = override.strip().lower()
        if text in {"true", "yes", "1", "on"}:
            return True
        if text in {"false", "no", "0", "off"}:
            return False

    weekdays = config.get("expiry_weekdays", [1])
    try:
        weekdays = {int(day) for day in weekdays}
    except Exception:
        weekdays = {1}
    return date_value.weekday() in weekdays


def get_trade_end_time():
    return EXPIRY_TRADE_END if is_expiry_day() else TRADE_END


def minutes_before_time(target_time, minutes):
    base = dt.datetime.combine(market_now().date(), target_time)
    return (base - dt.timedelta(minutes=minutes)).time()


def entry_cutoff_time():
    return minutes_before_time(get_trade_end_time(), ENTRY_CUTOFF_BUFFER_MINUTES)


def eod_exit_time():
    return minutes_before_time(get_trade_end_time(), EOD_EXIT_BUFFER_MINUTES)


def new_entries_allowed(now_time=None):
    now_time = now_time or market_now().time()
    cutoff = entry_cutoff_time()
    return now_time < cutoff


def eod_exit_due(now_time=None):
    now_time = now_time or market_now().time()
    return now_time >= eod_exit_time()


def get_market_session_status(now_dt=None):
    now_dt = now_dt or market_now()
    if not is_market_working_day(now_dt):
        reason = "Weekend" if now_dt.weekday() >= 5 else f"Market holiday {market_day_text(now_dt)}"
        return False, reason

    now_time = now_dt.time()
    trade_end_time = get_trade_end_time()
    if now_time < ANALYSIS_START:
        return False, f"Before market analysis time {ANALYSIS_START.strftime('%H:%M')}"
    if now_time > trade_end_time:
        return False, f"After trade end time {trade_end_time.strftime('%H:%M')}"
    return True, "Market session active"


def is_after_time(value, target):
    return value.hour > target.hour or (value.hour == target.hour and value.minute >= target.minute)


def get_server_url_hints():
    hints = ["http://127.0.0.1:8765"]
    port = int(config.get("port", 8765))
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if ":" in ip:
                continue
            if ip.startswith(("127.", "169.254.")):
                continue
            url = f"http://{ip}:{port}"
            if url not in hints:
                hints.append(url)
    except Exception:
        pass
    return hints


def get_signal(price):
    global last_confidence, last_score, last_signal, last_trend, last_supertrend
    if not orb_set:
        last_signal = "WAIT"
        update_trade_suggestion(None, "NONE", 0, 0, "ORB not set yet", price)
        return None, "NONE", 0
    df = get_indicators()
    if df is None:
        last_signal = "WAIT"
        update_trade_suggestion(None, "NONE", 0, 0, "Waiting for indicator candles", price)
        return None, "NONE", 0
    trend = predict_trend()
    last_trend = trend
    # Use only fully closed 1-minute candles for confirmation.
    # The latest row can still be forming, which was causing false "missing CANDLE".
    last = df.iloc[-2]
    c1 = df.iloc[-3]
    c2 = df.iloc[-2]
    vwap = float(last["VWAP"])
    ema9 = float(last["EMA9"])
    ema21 = float(last["EMA21"])
    supertrend_value = float(last["SUPERTREND"]) if not pd.isna(last.get("SUPERTREND")) else None
    supertrend_dir = str(last.get("SUPERTREND_DIR") or "NEUTRAL")
    last_supertrend = supertrend_dir
    gap_day = update_gap_day_mode(df)
    ce_orb_rule = price > (orb_high + ORB_BREAK_BUFFER_POINTS) and c2["close"] > orb_high
    pe_orb_rule = price < (orb_low - ORB_BREAK_BUFFER_POINTS) and c2["close"] < orb_low
    ce_score = 0
    pe_score = 0
    if price > vwap:
        ce_score += 1
    if supertrend_dir == "UP":
        ce_score += 1
    if ema9 > ema21 and trend == "UPTREND":
        ce_score += 1
    if not gap_day and ce_orb_rule:
        ce_score += 1
    if has_strong_two_candle_momentum(c1, c2, "CE"):
        ce_score += 1
    if price < vwap:
        pe_score += 1
    if supertrend_dir == "DOWN":
        pe_score += 1
    if ema9 < ema21 and trend == "DOWNTREND":
        pe_score += 1
    if not gap_day and pe_orb_rule:
        pe_score += 1
    if has_strong_two_candle_momentum(c1, c2, "PE"):
        pe_score += 1
    signal, trade_type, confidence, reason = choose_rule_signal(
        price, vwap, ema9, ema21, trend, supertrend_dir, c1, c2, ce_score, pe_score
    )
    if signal:
        timing_ok, timing_reason = entry_timing_guard(df, signal, price, vwap, ema9)
        if not timing_ok:
            reason = timing_reason
            signal = None
            trade_type = "NONE"
            confidence = 0
    last_confidence = confidence
    last_score = max(ce_score, pe_score)
    last_signal = signal or "WAIT"
    update_trade_suggestion(signal, trade_type, last_score, confidence, reason, price)
    if last_trade_suggestion:
        last_trade_suggestion["supertrend"] = supertrend_dir
        last_trade_suggestion["supertrend_value"] = supertrend_value
        last_trade_suggestion["gap_day"] = gap_day_summary()
    score_base = 4 if gap_day else 5
    gui_log(
        f"Decision | Signal: {last_signal} | Type: {trade_type} | Confidence: {confidence}% | "
        f"Score: {last_score}/{score_base} | ST:{supertrend_dir} | {gap_day_summary()} | {reason}"
    )
    return signal, trade_type, last_score


def update_trade_suggestion(signal, trade_type, score, confidence, reason, spot_price=None, option=None):
    global last_trade_suggestion
    now_text = market_now().isoformat(timespec="seconds")
    if not signal:
        last_trade_suggestion = {
            "action": "WAIT",
            "summary": f"WAIT | Score {score}/5 | {reason}",
            "signal": "WAIT",
            "trade_type": trade_type or "NONE",
            "score": score,
            "confidence": confidence,
            "reason": reason,
            "spot": spot_price,
            "timestamp": now_text,
        }
        return last_trade_suggestion

    suggestion = {
        "action": "BUY",
        "summary": f"BUY {signal} {trade_type} | Score {score}/5 | Confidence {confidence}%",
        "signal": signal,
        "trade_type": trade_type,
        "score": score,
        "confidence": confidence,
        "reason": reason,
        "spot": spot_price,
        "timestamp": now_text,
    }
    if option:
        lot_size = int(option.get("lot_size", FAST_LOT_SIZE) or FAST_LOT_SIZE)
        premium = float(option.get("premium") or 0)
        qty, max_lots = get_max_affordable_qty(premium, lot_size) if premium > 0 else (0, 0)
        cost = premium * qty
        target_price = premium * (1 + (EXPIRY_TARGET_PERCENT if is_expiry_day() else TARGET_PERCENT) / 100) if premium else 0
        breakeven_charges = calculate_option_charges(premium, premium, qty, entry_qty=qty, exchange=option.get("exchange"), symbol=option.get("symbol", ""))
        target_charges = calculate_option_charges(premium, target_price, qty, entry_qty=qty, exchange=option.get("exchange"), symbol=option.get("symbol", ""))
        breakeven_price = premium + ((breakeven_charges["total"] / qty) if qty else 0)
        suggestion.update({
            "symbol": option.get("symbol"),
            "strike": option.get("strike"),
            "premium": premium,
            "lot_size": lot_size,
            "qty": qty,
            "max_lots": max_lots,
            "cost": cost,
            "estimated_charges": target_charges["total"],
            "breakeven": breakeven_price,
            "sl": premium * (1 - (EXPIRY_SL_PERCENT if is_expiry_day() else SL_PERCENT) / 100) if premium else None,
            "target": target_price if premium else None,
        })
        suggestion["summary"] = (
            f"BUY {signal} {trade_type} | {option.get('symbol')} | "
            f"Premium {premium:.2f} | Qty {qty} | BE {breakeven_price:.2f} | Score {score}/5"
        )
    last_trade_suggestion = suggestion
    return suggestion


def parse_expiry_series(series):
    parsed = pd.to_datetime(series, format="%d%b%Y", errors="coerce")
    if parsed.isna().any():
        fallback = pd.to_datetime(series, errors="coerce")
        parsed = parsed.fillna(fallback)
    return parsed


def get_master():
    global master_cache
    if master_cache is not None:
        return master_cache.copy()
    if os.path.exists(MASTER_CACHE_PATH):
        with open(MASTER_CACHE_PATH, "r", encoding="utf-8") as file:
            master_cache = pd.DataFrame(json.load(file))
        return master_cache.copy()
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    data = requests.get(url, timeout=20).json()
    with open(MASTER_CACHE_PATH, "w", encoding="utf-8") as file:
        json.dump(data, file)
    master_cache = pd.DataFrame(data)
    return master_cache.copy()


def unique_strikes(strikes):
    result = []
    for strike in strikes:
        strike = int(strike)
        if strike not in result:
            result.append(strike)
    return result


def build_option_strike_priority(signal, spot_price):
    step = 50
    atm_strike = round(spot_price / step) * step
    lower_strike = int(spot_price // step) * step
    upper_strike = lower_strike + step
    if signal == "CE":
        nearest_otm = upper_strike if spot_price < upper_strike else upper_strike + step
        otm_side = [nearest_otm + (step * i) for i in range(0, 7)]
        fallback_side = [atm_strike - (step * i) for i in range(0, 5)]
    else:
        nearest_otm = lower_strike if spot_price > lower_strike else lower_strike - step
        otm_side = [nearest_otm - (step * i) for i in range(0, 7)]
        fallback_side = [atm_strike + (step * i) for i in range(0, 5)]
    return unique_strikes([nearest_otm, atm_strike] + otm_side + fallback_side)


def get_best_affordable_option(signal, spot_price):
    global last_option_selection_reason
    last_option_selection_reason = f"{signal} option check started"
    master = get_master()
    df = master[
        (master["name"] == "NIFTY")
        & (master["exch_seg"] == "NFO")
        & (master["instrumenttype"].str.contains("OPT", na=False))
        & (master["symbol"].str.endswith(signal))
    ].copy()
    df["expiry_dt"] = parse_expiry_series(df["expiry"])
    df["strike_num"] = pd.to_numeric(df["strike"], errors="coerce") / 100
    df = df.dropna(subset=["expiry_dt", "strike_num"])
    df = df[df["expiry_dt"] >= pd.Timestamp.today().normalize()]
    df = df.sort_values("expiry_dt")
    if df.empty:
        last_option_selection_reason = f"No live {signal} option contracts found in scrip master"
        gui_log(f"Option blocked | {last_option_selection_reason}")
        return None

    near_miss = None
    blocked_count = 0
    checked_count = 0
    ltp_fail_count = 0
    below_min_count = 0
    too_costly_count = 0
    missing_strike_count = 0
    skip_notes = []

    for priority, strike in enumerate(build_option_strike_priority(signal, spot_price)):
        temp = df[df["strike_num"] == strike]
        if temp.empty:
            missing_strike_count += 1
            continue
        row = temp.iloc[0]
        checked_count += 1
        option = {
            "symbol": row["symbol"],
            "token": row["token"],
            "exchange": row["exch_seg"],
            "strike": strike,
            "lot_size": int(float(row["lotsize"])),
            "priority": priority,
        }
        block_reason = option_reentry_block_reason(signal, option)
        if block_reason:
            blocked_count += 1
            if len(skip_notes) < 3:
                skip_notes.append(f"{option['symbol']} blocked: {block_reason}")
            continue
        premium = get_ltp(option["exchange"], option["symbol"], option["token"])
        if premium is None:
            ltp_fail_count += 1
            if len(skip_notes) < 3:
                skip_notes.append(f"{option['symbol']} LTP unavailable")
            continue
        if premium < MIN_PREMIUM:
            below_min_count += 1
            if len(skip_notes) < 3:
                skip_notes.append(f"{option['symbol']} premium {premium:.2f} below min {MIN_PREMIUM:.2f}")
            continue
        option["premium"] = premium
        option["cost"] = premium * option["lot_size"]
        option["affordable_lots"] = int(capital // option["cost"]) if option["cost"] > 0 else 0
        if option["cost"] <= capital:
            last_option_selection_reason = (
                f"Selected {option['symbol']} | premium {premium:.2f} | "
                f"lot {option['lot_size']} | cost {option['cost']:.2f}"
            )
            gui_log(f"Option ready | {last_option_selection_reason}")
            return option
        too_costly_count += 1
        if len(skip_notes) < 3:
            skip_notes.append(f"{option['symbol']} cost {option['cost']:.2f} > capital {capital:.2f}")
        extra_needed = max(0, option["cost"] - capital)
        if 0 < extra_needed <= EXTRA_CAPITAL_ALERT_LIMIT and near_miss is None:
            near_miss = {**option, "extra_needed": extra_needed}
    if near_miss:
        last_option_selection_reason = (
            f"Need approx {near_miss['extra_needed']:.2f} extra for {near_miss['symbol']} "
            f"(premium {near_miss.get('premium', 0):.2f})"
        )
        gui_log(f"Capital alert: {last_option_selection_reason}")
    else:
        detail = "; ".join(skip_notes) if skip_notes else "No matching strike passed filters"
        last_option_selection_reason = (
            f"No {signal} option selected | checked {checked_count} | missing strikes {missing_strike_count} | "
            f"LTP fail {ltp_fail_count} | below min {below_min_count} | too costly {too_costly_count} | "
            f"blocked {blocked_count} | {detail}"
        )
        gui_log(f"Option blocked | {last_option_selection_reason}")
    return None


def get_max_affordable_qty(premium, lot_size):
    max_lots = int(capital // (premium * lot_size))
    return max_lots * lot_size, max_lots


def get_qty(premium, trade_type, lot_size):
    trade_type = normalize_trade_type(trade_type)
    full_qty, max_lots = get_max_affordable_qty(premium, lot_size)
    if full_qty <= 0:
        return 0
    used_lots = qty_lots_for_trade_type(max_lots, trade_type)
    qty = used_lots * int(lot_size)
    gui_log(
        f"Qty plan | Type: {trade_type} | Premium: {premium:.2f} | "
        f"Lot: {lot_size} | Max lots: {max_lots} | Used lots: {used_lots} | Qty: {qty}"
    )
    return qty


def charges_enabled():
    return bool(config.get("charges_enabled", CHARGES_ENABLED))


def charge_value(name, default):
    try:
        return float(config.get(name, default))
    except Exception:
        return float(default)


def option_transaction_rate(exchange=None, symbol=""):
    text = f"{exchange or ''} {symbol or ''}".upper()
    if "BFO" in text or "SENSEX" in text or "BANKEX" in text:
        return charge_value("option_transaction_rate_bse", OPTION_TRANSACTION_RATE_BSE)
    return charge_value("option_transaction_rate_nse", OPTION_TRANSACTION_RATE_NSE)


def calculate_option_charges(entry_price, exit_price, qty, entry_qty=None, buy_order_count=1, sell_order_count=1, exchange=None, symbol=""):
    qty = int(qty or 0)
    if qty <= 0 or not charges_enabled():
        return {
            "brokerage": 0.0,
            "transaction": 0.0,
            "stt": 0.0,
            "stamp": 0.0,
            "sebi": 0.0,
            "ipft": 0.0,
            "gst": 0.0,
            "total": 0.0,
            "buy_turnover": 0.0,
            "sell_turnover": 0.0,
        }

    entry_price = float(entry_price or 0)
    exit_price = float(exit_price or 0)
    entry_qty = max(int(entry_qty or qty), qty)
    buy_fraction = min(1.0, qty / entry_qty)

    buy_turnover = entry_price * qty
    sell_turnover = exit_price * qty
    total_turnover = buy_turnover + sell_turnover

    brokerage_per_order = charge_value("brokerage_per_order", BROKERAGE_PER_ORDER)
    buy_brokerage = brokerage_per_order * max(1, int(buy_order_count or 1)) * buy_fraction
    sell_brokerage = brokerage_per_order * max(1, int(sell_order_count or 1))
    brokerage = buy_brokerage + sell_brokerage

    transaction = total_turnover * option_transaction_rate(exchange, symbol)
    stt = sell_turnover * charge_value("option_stt_sell_rate", OPTION_STT_SELL_RATE)
    stamp = buy_turnover * charge_value("option_stamp_buy_rate", OPTION_STAMP_BUY_RATE)
    sebi = total_turnover * charge_value("sebi_charge_rate", SEBI_CHARGE_RATE)
    ipft = total_turnover * charge_value("ipft_charge_rate", IPFT_CHARGE_RATE)
    gst = (brokerage + transaction + sebi + ipft) * charge_value("gst_rate", GST_RATE)

    total = brokerage + transaction + stt + stamp + sebi + ipft + gst
    return {
        "brokerage": round(brokerage, 2),
        "transaction": round(transaction, 2),
        "stt": round(stt, 2),
        "stamp": round(stamp, 2),
        "sebi": round(sebi, 2),
        "ipft": round(ipft, 4),
        "gst": round(gst, 2),
        "total": round(total, 2),
        "buy_turnover": round(buy_turnover, 2),
        "sell_turnover": round(sell_turnover, 2),
    }


def position_exit_charges(exit_price, qty=None):
    if position is None:
        return calculate_option_charges(0, 0, 0)
    option = position.get("option") or {}
    exit_qty = int(qty or position.get("qty", 0) or 0)
    return calculate_option_charges(
        position.get("entry", 0),
        exit_price,
        exit_qty,
        entry_qty=position.get("entry_qty") or position.get("qty") or exit_qty,
        buy_order_count=position.get("entry_order_count", 1),
        sell_order_count=1,
        exchange=option.get("exchange"),
        symbol=option.get("symbol", ""),
    )


def place_paper_trade(signal, premium, trade_type, option):
    global position, trades_taken
    trade_type = normalize_trade_type(trade_type)
    if not new_entries_allowed():
        gui_log(f"Entry blocked near EOD | Cutoff {entry_cutoff_time().strftime('%H:%M')} | Trade end {get_trade_end_time().strftime('%H:%M')}")
        update_trade_suggestion(None, "NONE", 0, 0, "Entry blocked near EOD", last_nifty_price)
        return
    lot_size = int(option.get("lot_size", FAST_LOT_SIZE))
    planned_full_qty, planned_full_lots = get_max_affordable_qty(premium, lot_size)
    qty = get_qty(premium, trade_type, lot_size)
    if qty <= 0:
        gui_log("Not enough capital for selected option")
        return
    sl_percent = EXPIRY_SL_PERCENT if is_expiry_day() else SL_PERCENT
    target_percent = EXPIRY_TARGET_PERCENT if is_expiry_day() else TARGET_PERCENT
    position = {
        "trade_id": market_now().strftime("OK%Y%m%d%H%M%S"),
        "entry_time": market_now().strftime("%H:%M:%S"),
        "entry_ts": time.time(),
        "signal": signal,
        "trade_type": trade_type,
        "option": option,
        "lot_size": lot_size,
        "planned_full_qty": planned_full_qty,
        "planned_full_lots": planned_full_lots,
        "entry": premium,
        "ltp": premium,
        "qty": qty,
        "entry_qty": qty,
        "entry_order_count": 1,
        "sl": premium * (1 - sl_percent / 100),
        "target": premium * (1 + target_percent / 100),
        "peak": premium,
        "partial_done": False,
        "target_extensions": 0,
    }
    entry_charge_estimate = calculate_option_charges(
        premium,
        premium,
        qty,
        entry_qty=qty,
        exchange=option.get("exchange"),
        symbol=option.get("symbol", ""),
    )
    entry_buy_charges = entry_charge_estimate.get("buy_charges", entry_charge_estimate.get("buy_total", 0))
    trades_taken += 1
    msg = (
        f"PAPER ENTRY\nType: {trade_type}\nSignal: {signal}\nSymbol: {option['symbol']}\n"
        f"Entry: {premium:.2f}\nQty: {qty}\nBuy Charges Est: {entry_buy_charges:.2f}\n"
        f"SL: {position['sl']:.2f}\nTarget: {position['target']:.2f}"
    )
    gui_log(msg)
    send_msg(msg)
    save_trade_event("ENTRY", {
        "reason": "PAPER ENTRY",
        "charges_total": entry_buy_charges,
        "buy_charges": entry_buy_charges,
        "buy_turnover": premium * qty,
        **position,
    })


def trade_day_text():
    return market_now().strftime("%Y%m%d")


def trade_file(prefix, extension):
    return os.path.join(TRADE_DIR, f"{prefix}_{trade_day_text()}.{extension}")


def append_csv_row(path, fieldnames, row):
    exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def save_trade_event(event_type, payload):
    charges = payload.get("charges") or {}
    row = {
        "timestamp": market_now().isoformat(timespec="seconds"),
        "event": event_type,
        "trade_id": payload.get("trade_id", ""),
        "mode": "PAPER",
        "trade_type": payload.get("trade_type", ""),
        "signal": payload.get("signal", ""),
        "symbol": (payload.get("option") or {}).get("symbol", ""),
        "entry": payload.get("entry", ""),
        "exit": payload.get("exit", ""),
        "ltp": payload.get("ltp", ""),
        "qty": payload.get("qty", ""),
        "pnl": payload.get("pnl", ""),
        "gross_pnl": payload.get("gross_pnl", payload.get("pnl", "")),
        "charges": payload.get("charges_total", charges.get("total", "")),
        "buy_charges": payload.get("buy_charges", charges.get("buy_charges", charges.get("buy_total", ""))),
        "sell_charges": payload.get("sell_charges", charges.get("sell_charges", charges.get("sell_total", ""))),
        "buy_turnover": payload.get("buy_turnover", charges.get("buy_turnover", "")),
        "sell_turnover": payload.get("sell_turnover", charges.get("sell_turnover", "")),
        "net_pnl": payload.get("net_pnl", payload.get("pnl", "")),
        "reason": payload.get("reason", ""),
        "capital": capital,
        "daily_pnl": daily_pnl,
    }
    append_csv_row(trade_file("trade_events", "csv"), list(row.keys()), row)
    with open(trade_file("trade_events", "jsonl"), "a", encoding="utf-8") as file:
        file.write(json.dumps(row, default=str) + "\n")


def save_closed_trade(row):
    fieldnames = [
        "date", "time", "exit_time", "mode", "trade_id", "type", "signal", "symbol",
        "entry", "exit", "qty", "gross_pnl", "charges", "net_pnl", "pnl",
        "buy_charges", "sell_charges", "buy_turnover", "sell_turnover",
        "brokerage", "stt", "transaction", "gst", "stamp", "sebi", "reason",
    ]
    append_csv_row(trade_file("closed_trades", "csv"), fieldnames, row)


def normalize_closed_trade_row(row):
    normalized = dict(row)
    for key in [
        "entry", "exit", "pnl", "gross_pnl", "charges", "net_pnl",
        "buy_charges", "sell_charges", "buy_turnover", "sell_turnover",
        "brokerage", "stt", "transaction", "gst", "stamp", "sebi",
    ]:
        try:
            normalized[key] = float(normalized.get(key, 0) or 0)
        except Exception:
            normalized[key] = 0.0
    if normalized.get("charges", 0) and not (normalized.get("buy_charges", 0) or normalized.get("sell_charges", 0)):
        normalized["buy_charges"] = normalized["charges"] / 2
        normalized["sell_charges"] = normalized["charges"] / 2
    if not normalized.get("net_pnl") and normalized.get("pnl"):
        normalized["net_pnl"] = normalized["pnl"]
    if not normalized.get("gross_pnl") and normalized.get("pnl"):
        normalized["gross_pnl"] = normalized["pnl"] + normalized.get("charges", 0)
    normalized["pnl"] = normalized.get("net_pnl", normalized.get("pnl", 0))
    try:
        normalized["qty"] = int(float(normalized.get("qty", 0) or 0))
    except Exception:
        normalized["qty"] = 0
    return normalized


def load_trade_history_from_disk():
    global trade_history, total_trades, winning_trades, losing_trades, daily_pnl, capital, trades_taken
    ensure_dirs()
    rows = []
    seen = set()
    for name in sorted(os.listdir(TRADE_DIR)):
        if not name.startswith("closed_trades_") or not name.endswith(".csv"):
            continue
        path = os.path.join(TRADE_DIR, name)
        try:
            with open(path, "r", newline="", encoding="utf-8") as file:
                for row in csv.DictReader(file):
                    normalized = normalize_closed_trade_row(row)
                    key = (
                        normalized.get("date", ""),
                        normalized.get("time", ""),
                        normalized.get("exit_time", ""),
                        normalized.get("trade_id", ""),
                        normalized.get("symbol", ""),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(normalized)
        except Exception as exc:
            gui_log(f"Closed trade load skipped {name}: {exc}")
    rows.sort(key=lambda item: f"{item.get('date', '')} {item.get('exit_time') or item.get('time', '')}")
    trade_history = rows
    total_trades = len(rows)
    winning_trades = sum(1 for trade in rows if float(trade.get("pnl", 0) or 0) > 0)
    losing_trades = total_trades - winning_trades
    today_text = market_day_text()
    today_rows = [trade for trade in rows if str(trade.get("date", "")) == today_text]
    daily_pnl = sum(float(trade.get("pnl", 0) or 0) for trade in today_rows)
    trades_taken = len(today_rows)
    capital = paper_capital + daily_pnl
    gui_log(f"Loaded closed trades: {len(trade_history)} | Today P&L rebuilt: {daily_pnl:.2f} | Capital: {capital:.2f}")


def update_trade_stats(pnl):
    global total_trades, winning_trades, losing_trades, loss_streak
    total_trades += 1
    if pnl > 0:
        winning_trades += 1
        loss_streak = 0
    else:
        losing_trades += 1
        loss_streak += 1


def record_trade(exit_price, gross_pnl, charges, net_pnl, reason):
    now = market_now()
    row = {
        "date": now.strftime("%Y-%m-%d"),
        "time": position.get("entry_time", now.strftime("%H:%M:%S")),
        "exit_time": now.strftime("%H:%M:%S"),
        "mode": "PAPER",
        "trade_id": position.get("trade_id", ""),
        "type": position.get("trade_type", "FULL"),
        "signal": position["signal"],
        "symbol": position.get("option", {}).get("symbol", "DEMO"),
        "entry": position["entry"],
        "exit": exit_price,
        "qty": position["qty"],
        "gross_pnl": gross_pnl,
        "charges": charges.get("total", 0),
        "net_pnl": net_pnl,
        "pnl": net_pnl,
        "buy_charges": charges.get("buy_charges", charges.get("buy_total", 0)),
        "sell_charges": charges.get("sell_charges", charges.get("sell_total", 0)),
        "buy_turnover": charges.get("buy_turnover", position["entry"] * position["qty"]),
        "sell_turnover": charges.get("sell_turnover", exit_price * position["qty"]),
        "brokerage": charges.get("brokerage", 0),
        "stt": charges.get("stt", 0),
        "transaction": charges.get("transaction", 0),
        "gst": charges.get("gst", 0),
        "stamp": charges.get("stamp", 0),
        "sebi": charges.get("sebi", 0),
        "reason": reason,
    }
    trade_history.append(row)
    save_closed_trade(row)
    save_trade_event("EXIT", {
        "exit": exit_price,
        "pnl": net_pnl,
        "gross_pnl": gross_pnl,
        "charges": charges,
        "net_pnl": net_pnl,
        "reason": reason,
        **position,
    })


def close_position(exit_price, reason):
    global position, capital, daily_pnl
    if position is None:
        return
    exit_qty = int(position["qty"])
    gross_pnl = (exit_price - position["entry"]) * exit_qty
    charges = position_exit_charges(exit_price, exit_qty)
    net_pnl = gross_pnl - charges["total"]
    capital += net_pnl
    daily_pnl += net_pnl
    update_trade_stats(net_pnl)
    record_trade(exit_price, gross_pnl, charges, net_pnl, reason)
    register_reentry_block(reason, net_pnl)
    msg = (
        f"PAPER EXIT\nReason: {reason}\nSymbol: {position.get('option', {}).get('symbol', 'DEMO')}\n"
        f"Exit: {exit_price:.2f}\nGross P&L: {gross_pnl:.2f}\nCharges: {charges['total']:.2f}\n"
        f"Net P&L: {net_pnl:.2f}\nCapital: {capital:.2f}"
    )
    position = None
    gui_log(msg)
    send_msg(msg)
    return net_pnl


def update_trailing_sl():
    if position is None:
        return
    entry = position["entry"]
    ltp = position["ltp"]
    if ltp > position["peak"]:
        position["peak"] = ltp
    profit_percent = ((ltp - entry) / entry) * 100
    if profit_percent > 8 and position["sl"] < entry:
        position["sl"] = entry
        gui_log("SL moved to cost")
    if profit_percent > 15:
        position["sl"] = max(position["sl"], entry * 1.05)
    if profit_percent > 20:
        gap = EXPIRY_TRAIL_GAP if is_expiry_day() else 5
        position["sl"] = max(position["sl"], ltp * (1 - gap / 100))


def reversal_min_hold_seconds():
    try:
        return max(0.0, float(config.get("reversal_min_hold_seconds", REVERSAL_MIN_HOLD_SECONDS)))
    except Exception:
        return float(REVERSAL_MIN_HOLD_SECONDS)


def reversal_confirm_candles():
    try:
        return max(2, int(config.get("reversal_confirm_candles", REVERSAL_CONFIRM_CANDLES)))
    except Exception:
        return int(REVERSAL_CONFIRM_CANDLES)


def reversal_min_loss_percent():
    try:
        return max(0.0, float(config.get("reversal_min_loss_percent", REVERSAL_MIN_LOSS_PERCENT)))
    except Exception:
        return float(REVERSAL_MIN_LOSS_PERCENT)


def position_age_seconds():
    if position is None:
        return 0.0
    try:
        return max(0.0, time.time() - float(position.get("entry_ts")))
    except Exception:
        return reversal_min_hold_seconds()


def position_loss_percent():
    if position is None:
        return 0.0
    try:
        entry = float(position.get("entry") or 0)
        ltp = float(position.get("ltp") or entry)
        if entry <= 0:
            return 0.0
        return ((entry - ltp) / entry) * 100
    except Exception:
        return 0.0


def confirmed_reversal_candles(df, direction):
    count = reversal_confirm_candles()
    if df is None or len(df) < count:
        return False
    recent = df.tail(count)
    if direction == "RED":
        return bool((recent["close"] < recent["open"]).all())
    if direction == "GREEN":
        return bool((recent["close"] > recent["open"]).all())
    return False


def should_exit_on_index_reversal(current_price):
    if position is None or current_price is None:
        return False, ""
    df = get_indicators()
    if df is None or len(df) < max(3, reversal_confirm_candles()):
        return False, ""
    last = df.iloc[-1]
    vwap = float(last["VWAP"])
    ema21 = float(last["EMA21"])
    supertrend_dir = str(last.get("SUPERTREND_DIR") or "NEUTRAL")
    signal = position.get("signal")
    age = position_age_seconds()
    loss_percent = position_loss_percent()
    if age < reversal_min_hold_seconds() and loss_percent < reversal_min_loss_percent():
        return False, ""
    if signal == "CE":
        red_confirm = confirmed_reversal_candles(df, "RED")
        lost_vwap = current_price < vwap and float(last["close"]) < vwap
        st_flip = supertrend_filter_enabled() and supertrend_dir == "DOWN"
        failed_orb = orb_high is not None and current_price < (orb_high - ORB_BREAK_BUFFER_POINTS)
        lost_ema21 = float(last["close"]) < ema21
        if red_confirm and lost_vwap and (st_flip or failed_orb):
            return True, f"REVERSAL EXIT: CE confirmed {reversal_confirm_candles()} red candles + VWAP loss"
        if st_flip and failed_orb and lost_ema21:
            return True, "REVERSAL EXIT: CE confirmed Supertrend flip + ORB fail + EMA21 loss"
    if signal == "PE":
        green_confirm = confirmed_reversal_candles(df, "GREEN")
        lost_vwap = current_price > vwap and float(last["close"]) > vwap
        st_flip = supertrend_filter_enabled() and supertrend_dir == "UP"
        failed_orb = orb_low is not None and current_price > (orb_low + ORB_BREAK_BUFFER_POINTS)
        lost_ema21 = float(last["close"]) > ema21
        if green_confirm and lost_vwap and (st_flip or failed_orb):
            return True, f"REVERSAL EXIT: PE confirmed {reversal_confirm_candles()} green candles + VWAP loss"
        if st_flip and failed_orb and lost_ema21:
            return True, "REVERSAL EXIT: PE confirmed Supertrend flip + ORB fail + EMA21 loss"
    return False, ""


def stop_and_reverse_enabled():
    value = config.get("stop_and_reverse_enabled", STOP_AND_REVERSE_ENABLED)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def stop_and_reverse_min_score():
    try:
        return max(3, int(config.get("stop_and_reverse_min_score", STOP_AND_REVERSE_MIN_SCORE)))
    except Exception:
        return int(STOP_AND_REVERSE_MIN_SCORE)


def stop_and_reverse_trade_type():
    return normalize_trade_type(config.get("stop_and_reverse_trade_type", STOP_AND_REVERSE_TRADE_TYPE))


def stop_and_reverse_cooldown_minutes():
    try:
        return max(1.0, float(config.get("stop_and_reverse_cooldown_minutes", STOP_AND_REVERSE_COOLDOWN_MINUTES)))
    except Exception:
        return float(STOP_AND_REVERSE_COOLDOWN_MINUTES)


def opposite_signal(signal):
    signal = str(signal or "").upper()
    if signal == "CE":
        return "PE"
    if signal == "PE":
        return "CE"
    return None


def try_stop_and_reverse(old_signal, current_price, exit_reason):
    global post_exit_wait_until, reverse_entry_block_until, last_reverse_trade_ts
    reverse_signal = opposite_signal(old_signal)
    if not stop_and_reverse_enabled() or reverse_signal is None:
        return False
    if current_price is None:
        gui_log("Stop-and-reverse skipped: NIFTY price unavailable")
        return False
    if not new_entries_allowed():
        gui_log("Stop-and-reverse skipped: entry cutoff reached")
        return False
    now_ts = time.time()
    if reverse_entry_block_until and now_ts < reverse_entry_block_until:
        gui_log(f"Stop-and-reverse skipped: cooldown {block_remaining_text(reverse_entry_block_until)}")
        return False

    saved_wait_until = post_exit_wait_until
    post_exit_wait_until = 0
    try:
        signal, suggested_type, score = get_signal(current_price)
    finally:
        if position is None:
            post_exit_wait_until = saved_wait_until

    min_score = stop_and_reverse_min_score()
    if signal != reverse_signal or score < min_score:
        gui_log(
            f"Stop-and-reverse skipped: opposite {reverse_signal} not confirmed | "
            f"got {signal or 'WAIT'} score {score}/{min_score}"
        )
        return False

    trade_type = stop_and_reverse_trade_type()
    if normalize_trade_type(suggested_type, allow_none=True) == "FULL" and trade_type != "HALF":
        trade_type = "FULL"

    option = get_best_affordable_option(reverse_signal, current_price)
    if option is None:
        gui_log(f"Stop-and-reverse skipped: no affordable {reverse_signal} option")
        return False

    gui_log(
        f"Stop-and-reverse confirmed | Old: {old_signal} exit | New: {reverse_signal} {trade_type} | "
        f"Score: {score}/5 | Reason: {exit_reason}"
    )
    placed_before = position is not None
    place_paper_trade(reverse_signal, option["premium"], trade_type, option)
    if position is not None and not placed_before:
        last_reverse_trade_ts = time.time()
        reverse_entry_block_until = last_reverse_trade_ts + (stop_and_reverse_cooldown_minutes() * 60)
        position["reverse_from"] = old_signal
        position["reverse_reason"] = exit_reason
        save_trade_event("STOP_AND_REVERSE", {"old_signal": old_signal, "new_signal": reverse_signal, "reason": exit_reason, **position})
        return True
    return False


def get_position_lot_size():
    if position is None:
        return FAST_LOT_SIZE
    return int((position.get("option") or {}).get("lot_size") or position.get("lot_size") or FAST_LOT_SIZE)


def check_partial_exit():
    global capital, daily_pnl
    if position is None or position.get("partial_done"):
        return
    entry = position["entry"]
    ltp = position["ltp"]
    profit_percent = ((ltp - entry) / entry) * 100
    partial_trigger = (EXPIRY_TARGET_PERCENT if is_expiry_day() else TARGET_PERCENT) + 5
    if profit_percent < partial_trigger:
        return
    lot_size = get_position_lot_size()
    current_qty = int(position.get("qty", 0) or 0)
    if current_qty < lot_size * 2:
        return
    exit_lots = max(1, (current_qty // lot_size) // 2)
    exit_qty = exit_lots * lot_size
    if exit_qty <= 0 or current_qty - exit_qty < lot_size:
        return
    gross_pnl = (ltp - entry) * exit_qty
    charges = position_exit_charges(ltp, exit_qty)
    net_pnl = gross_pnl - charges["total"]
    capital += net_pnl
    daily_pnl += net_pnl
    position["qty"] -= exit_qty
    position["closed_qty"] = int(position.get("closed_qty", 0) or 0) + exit_qty
    position["partial_done"] = True
    msg = f"PARTIAL EXIT | Qty: {exit_qty} | Exit: {ltp:.2f} | Gross: {gross_pnl:.2f} | Charges: {charges['total']:.2f} | Net: {net_pnl:.2f}"
    gui_log(msg)
    send_msg(msg)
    save_trade_event("PARTIAL_EXIT", {
        "trade_id": position.get("trade_id", ""),
        "trade_type": position.get("trade_type", "FULL"),
        "signal": position["signal"],
        "option": position.get("option"),
        "entry": entry,
        "exit": ltp,
        "ltp": ltp,
        "qty": exit_qty,
        "pnl": net_pnl,
        "gross_pnl": gross_pnl,
        "charges": charges,
        "net_pnl": net_pnl,
        "reason": "PARTIAL EXIT",
    })


def extend_target_if_market_has_potential(current_price, premium):
    if position is None or current_price is None:
        return False
    extensions = int(position.get("target_extensions", 0) or 0)
    if extensions >= TARGET_EXTENSION_MAX_COUNT:
        return False
    signal, trade_type, score = get_signal(current_price)
    if signal != position.get("signal") or trade_type != "FULL":
        return False
    gap = EXPIRY_TRAIL_GAP if is_expiry_day() else 5
    position["target_extensions"] = extensions + 1
    position["target"] = max(position["target"], premium * (1 + DYNAMIC_TARGET_BOOST_PERCENT / 100))
    position["sl"] = max(position["sl"], position["entry"], premium * (1 - gap / 100))
    msg = f"Target extended on strong market\nSignal: {signal} | Score: {score}/5\nNew Target: {position['target']:.2f} | New SL: {position['sl']:.2f}"
    gui_log(msg)
    send_msg(msg)
    save_trade_event("TARGET_EXTEND", {"reason": "TARGET EXTENDED", **position})
    return True


def manage_paper_trade(premium, current_price=None):
    if position is None:
        return
    position["ltp"] = premium
    old_signal = position.get("signal")
    reverse_exit, reverse_reason = should_exit_on_index_reversal(current_price)
    if reverse_exit:
        close_position(premium, reverse_reason)
        try_stop_and_reverse(old_signal, current_price, reverse_reason)
        return
    update_trailing_sl()
    if premium <= position["sl"]:
        close_position(premium, "SL HIT")
    elif premium >= position["target"]:
        if not extend_target_if_market_has_potential(current_price, premium):
            close_position(premium, "TARGET HIT")
    else:
        check_partial_exit()


def get_live_equity():
    if position is None:
        return capital
    ltp = position.get("ltp", position.get("entry", 0))
    gross_pnl = (ltp - position["entry"]) * position["qty"]
    charges = position_exit_charges(ltp, position["qty"])
    return capital + gross_pnl - charges["total"]


def check_risk_limits():
    global running
    live_equity = get_live_equity()
    if live_equity <= paper_capital * (1 - MAX_DAILY_LOSS):
        if position is not None:
            close_position(position.get("ltp", position.get("entry", 0)), "DAILY LOSS LIMIT")
        gui_log("Daily loss limit hit. Bot stopping.")
        running = False
        return

    lock_changed = update_profit_lock_floor(live_equity)
    if not lock_changed and daily_profit_floor is not None and live_equity < daily_profit_floor:
        if position is not None:
            close_position(position.get("ltp", position.get("entry", 0)), "DAILY PROFIT FLOOR")
        gui_log("Profit floor protected. Bot stopping.")
        running = False


def safe_sleep(seconds):
    for _ in range(seconds):
        if not running:
            break
        time.sleep(1)


def bot_loop():
    global running, bot_running_lock, last_nifty_price, last_trend
    if bot_running_lock:
        gui_log("Duplicate bot blocked")
        return
    bot_running_lock = True
    try:
        angel_login()
        gui_log("Cloud paper bot started")
        while running:
            try:
                now_dt = market_now()
                now = now_dt.time()
                session_open, session_reason = get_market_session_status(now_dt)
                if not session_open:
                    if position is not None and now > get_trade_end_time():
                        close_position(position.get("ltp", position.get("entry", 0)), "EOD FORCE EXIT")
                        running = False
                        gui_log("EOD force exit done. Bot stopping.")
                        continue
                    gui_log(session_reason)
                    safe_sleep(30)
                    continue
                current_price = get_nifty_price()
                if current_price is None:
                    safe_sleep(10)
                    continue
                last_nifty_price = current_price
                last_trend = predict_trend()
                if not orb_set and now > dt.time(9, 20):
                    set_orb()
                if ANALYSIS_START <= now < TRADE_START:
                    gui_log(f"Analysis mode | NIFTY: {current_price:.2f}")
                    safe_sleep(10)
                    continue
                if position is not None and eod_exit_due(now):
                    option = position.get("option")
                    premium = get_ltp(option["exchange"], option["symbol"], option["token"]) if option else current_price * 0.01
                    if premium is not None:
                        close_position(premium, "EOD FORCE EXIT")
                    running = False
                    gui_log("EOD force exit done. Bot stopping.")
                    safe_sleep(2)
                    continue
                if position:
                    option = position.get("option")
                    premium = get_ltp(option["exchange"], option["symbol"], option["token"]) if option else current_price * 0.01
                    if premium is not None:
                        manage_paper_trade(premium, current_price)
                else:
                    if not new_entries_allowed(now):
                        gui_log(f"New entries blocked near EOD | Cutoff {entry_cutoff_time().strftime('%H:%M')}")
                        safe_sleep(10)
                        continue
                    signal, trade_type, score = get_signal(current_price)
                    if signal:
                        gui_log(
                            f"ENTRY SIGNAL FOUND | {signal} {trade_type} | "
                            f"Score {score}/5 | Confidence {last_confidence}% | NIFTY {current_price:.2f}"
                        )
                        option = get_best_affordable_option(signal, current_price)
                        if option:
                            update_trade_suggestion(signal, trade_type, score, last_confidence, "Tradable option found", current_price, option)
                            place_paper_trade(signal, option["premium"], trade_type, option)
                        else:
                            reason = last_option_selection_reason or f"{signal} setup found but no affordable option"
                            gui_log(f"ENTRY BLOCKED | {signal} {trade_type} | {reason}")
                            update_trade_suggestion(None, "NONE", score, last_confidence, f"{signal} setup blocked: {reason}", current_price)
                    else:
                        gui_log(f"No signal | NIFTY: {current_price:.2f} | Score: {score}/5")
                check_risk_limits()
                safe_sleep(10)
            except Exception as exc:
                gui_log(f"Loop error: {exc}")
                safe_sleep(10)
    except Exception as exc:
        gui_log(f"Bot error: {exc}")
    finally:
        bot_running_lock = False
        running = False


def start_bot():
    global running, bot_thread, daily_target_alert_done, daily_profit_floor, daily_profit_lock_level
    if running:
        return
    running = True
    daily_target_alert_done = False
    daily_profit_floor = None
    daily_profit_lock_level = 0.0
    bot_thread = threading.Thread(target=bot_loop, daemon=True)
    bot_thread.start()
    gui_log("Start requested")
    send_msg("Option King AI phone server: bot start requested")


def stop_bot():
    global running
    running = False
    gui_log("Stop requested")
    send_msg("Option King AI phone server: bot stop requested")


def update_capital(new_capital):
    global capital, paper_capital, daily_pnl, trades_taken, daily_target_alert_done, daily_profit_floor, daily_profit_lock_level
    paper_capital = float(new_capital)
    capital = paper_capital
    daily_pnl = 0.0
    trades_taken = 0
    daily_target_alert_done = False
    daily_profit_floor = None
    daily_profit_lock_level = 0.0
    config["capital"] = paper_capital
    save_cloud_config()
    gui_log(f"Capital updated: {capital:.2f}")
    send_msg(f"Option King AI phone server: capital updated to {capital:.2f}")


def health_payload(test_angel=False):
    global last_health_summary
    now_dt = market_now()
    session_open, session_reason = get_market_session_status(now_dt)
    angel_configured = all(config.get(key) for key in ["api_key", "client_id", "password", "totp_secret"])
    telegram_configured = bool(config.get("telegram_token") and config.get("chat_id"))
    issues = []
    angel_status = "CONFIGURED" if angel_configured else "MISSING"

    if not angel_configured:
        issues.append("Angel credentials missing")
    elif test_angel:
        try:
            angel_login()
            angel_status = "OK"
        except Exception as exc:
            angel_status = f"ERROR: {exc}"
            issues.append("Angel login failed")

    if not telegram_configured:
        issues.append("Telegram missing")
    if not api_token():
        issues.append("API token missing")
    if not is_market_working_day(now_dt):
        issues.append(session_reason)
    if not AUTO_START_BOT:
        issues.append("Auto start disabled")

    status = "READY" if not issues or issues == [session_reason] else "CHECK"
    if not is_market_working_day(now_dt):
        status = "MARKET CLOSED"

    last_health_summary = f"{status} | {session_reason}"
    return {
        "status": status,
        "summary": last_health_summary,
        "timestamp": now_dt.isoformat(timespec="seconds"),
        "server_version": SERVER_VERSION,
        "server_running": True,
        "bot_running": running,
        "market_open": session_open,
        "market_session": session_reason,
        "market_working_day": is_market_working_day(now_dt),
        "expiry_day": is_expiry_day(now_dt),
        "auto_start_bot": AUTO_START_BOT,
        "angel": angel_status,
        "telegram": "SET" if telegram_configured else "MISSING",
        "api_token": "SET" if api_token() else "MISSING",
        "capital": capital,
        "live_equity": get_live_equity(),
        "daily_pnl": daily_pnl,
        "position_open": position is not None,
        "urls": get_server_url_hints(),
        "master_cache": "SET" if os.path.exists(MASTER_CACHE_PATH) else "MISSING",
        "trade_dir": TRADE_DIR,
        "auto_update": last_update_status,
        "charges_enabled": charges_enabled(),
        "morning_watchdog": {
            "ready_time": MORNING_WATCHDOG_READY_TIME.strftime("%H:%M"),
            "start_check_time": MORNING_WATCHDOG_START_CHECK_TIME.strftime("%H:%M"),
            "final_check_time": MORNING_WATCHDOG_FINAL_CHECK_TIME.strftime("%H:%M"),
            "ready_sent_today": morning_watchdog_ready_done_for_day == market_day_text(now_dt),
            "start_check_sent_today": morning_watchdog_start_done_for_day == market_day_text(now_dt),
            "final_check_sent_today": morning_watchdog_final_done_for_day == market_day_text(now_dt),
        },
        "issues": issues,
    }


def build_health_text(test_angel=False):
    health = health_payload(test_angel=test_angel)
    issues = health.get("issues") or []
    lines = [
        "OPTION KING AI HEALTH",
        "",
        f"Status: {health['status']}",
        f"Time: {health['timestamp']}",
        f"Server: ON",
        f"Version: {health['server_version']}",
        f"Bot: {'RUNNING' if health['bot_running'] else 'STOPPED'}",
        f"Market: {health['market_session']}",
        f"Expiry Day: {'YES' if health.get('expiry_day') else 'NO'}",
        f"Auto Start: {'ON' if health['auto_start_bot'] else 'OFF'}",
        f"Angel Login: {health['angel']}",
        f"Telegram: {health['telegram']}",
        f"Capital: {health['capital']:.2f}",
        f"Live Equity: {health['live_equity']:.2f}",
        f"Daily P&L: {health['daily_pnl']:.2f}",
        f"Position: {'OPEN' if health['position_open'] else 'NONE'}",
        f"Auto Update: {health.get('auto_update', {}).get('summary', '--')}",
        "",
        "SERVER URLS",
        *(health.get("urls") or ["--"]),
        "",
        "ISSUES",
        *(issues or ["No blocking issue detected."]),
    ]
    return "\n".join(lines)


def check_daily_readiness_alert():
    global readiness_alert_done_for_day
    today_text = market_day_text()
    if readiness_alert_done_for_day == today_text:
        return
    now_dt = market_now()
    if not is_after_time(now_dt.time(), READINESS_ALERT_TIME):
        return
    readiness_alert_done_for_day = today_text
    text = "OPTION KING AI READY CHECK\n\n" + build_health_text(test_angel=True)
    gui_log("Daily readiness alert sent")
    send_msg(text)


def build_morning_watchdog_text(title, action_text):
    health = health_payload(test_angel=False)
    issues = health.get("issues") or []
    lines = [
        title,
        "",
        f"Time: {market_now().isoformat(timespec='seconds')}",
        f"Server: ON",
        f"Bot: {'RUNNING' if running else 'STOPPED'}",
        f"Auto Start: {'ON' if AUTO_START_BOT else 'OFF'}",
        f"Market: {health.get('market_session', '--')}",
        f"Angel: {health.get('angel', '--')}",
        f"Telegram: {health.get('telegram', '--')}",
        f"Capital: {capital:.2f}",
        f"Daily P&L: {daily_pnl:.2f}",
        f"Position: {'OPEN' if position is not None else 'NONE'}",
        f"Action: {action_text}",
        "",
        "ISSUES",
        *(issues or ["No blocking issue detected."]),
    ]
    return "\n".join(lines)


def check_morning_watchdog():
    global morning_watchdog_ready_done_for_day, morning_watchdog_start_done_for_day
    global morning_watchdog_final_done_for_day, auto_start_done_for_day

    now_dt = market_now()
    if not is_market_working_day(now_dt):
        return

    now_time = now_dt.time()
    if now_time > MORNING_WATCHDOG_END_TIME:
        return

    today_text = market_day_text(now_dt)

    if (
        morning_watchdog_ready_done_for_day != today_text
        and is_after_time(now_time, MORNING_WATCHDOG_READY_TIME)
    ):
        morning_watchdog_ready_done_for_day = today_text
        gui_log("Morning watchdog ready check sent")
        send_msg(
            build_morning_watchdog_text(
                "OPTION KING AI MORNING WATCHDOG",
                "Server awake. Bot will auto-start from 09:15 if conditions are OK.",
            )
        )

    if (
        morning_watchdog_start_done_for_day != today_text
        and is_after_time(now_time, MORNING_WATCHDOG_START_CHECK_TIME)
    ):
        morning_watchdog_start_done_for_day = today_text
        session_open, session_reason = get_market_session_status(now_dt)

        if AUTO_START_BOT and session_open and not running and position is None:
            gui_log("Morning watchdog rescue start triggered")
            send_msg(
                build_morning_watchdog_text(
                    "OPTION KING AI AUTO START WATCHDOG",
                    "Bot was not running after 09:15. Rescue start requested now.",
                )
            )
            auto_start_done_for_day = today_text
            start_bot()
        elif running:
            gui_log("Morning watchdog confirmed bot running")
            send_msg(
                build_morning_watchdog_text(
                    "OPTION KING AI AUTO START OK",
                    "Bot is running after market open.",
                )
            )
        else:
            gui_log(f"Morning watchdog start blocked: {session_reason}")
            send_msg(
                build_morning_watchdog_text(
                    "OPTION KING AI AUTO START BLOCKED",
                    f"Bot not started. Reason: {session_reason}",
                )
            )

    if (
        morning_watchdog_final_done_for_day != today_text
        and is_after_time(now_time, MORNING_WATCHDOG_FINAL_CHECK_TIME)
    ):
        morning_watchdog_final_done_for_day = today_text
        if running:
            title = "OPTION KING AI 09:20 CONFIRMED"
            action = "Bot is running. Morning setup OK."
        else:
            title = "OPTION KING AI 09:20 WARNING"
            action = "Bot is still stopped. Open mobile app/server logs and start manually."
        gui_log(title)
        send_msg(build_morning_watchdog_text(title, action))


def build_eod_report_text():
    today = market_day_text()
    today_trades = [trade for trade in trade_history if str(trade.get("date", "")) == today]
    total_pnl = sum(float(trade.get("pnl", 0) or 0) for trade in today_trades)
    wins = sum(1 for trade in today_trades if float(trade.get("pnl", 0) or 0) > 0)
    losses = sum(1 for trade in today_trades if float(trade.get("pnl", 0) or 0) <= 0)
    win_rate = (wins / len(today_trades) * 100) if today_trades else 0
    lines = [
        "OPTION KING AI EOD REPORT",
        "",
        f"Date: {today}",
        f"Capital: {capital:.2f}",
        f"Live Equity: {get_live_equity():.2f}",
        f"Daily P&L: {daily_pnl:.2f}",
        f"Closed Trades: {len(today_trades)}",
        f"Wins: {wins}",
        f"Losses: {losses}",
        f"Win Rate: {win_rate:.2f}%",
        f"Closed Trade P&L: {total_pnl:.2f}",
        "",
        "LAST TRADES",
    ]
    if today_trades:
        for trade in today_trades[-10:]:
            lines.append(
                f"{trade.get('time')}->{trade.get('exit_time')} | {trade.get('signal')} | "
                f"{trade.get('symbol')} | P&L {float(trade.get('pnl', 0) or 0):.2f} | {trade.get('reason')}"
            )
    else:
        lines.append("No closed trades today.")
    return "\n".join(lines)


def check_eod_report_alert():
    global eod_report_done_for_day
    today_text = market_day_text()
    if eod_report_done_for_day == today_text:
        return
    now_dt = market_now()
    if not is_market_working_day(now_dt):
        return
    if not is_after_time(now_dt.time(), EOD_REPORT_TIME):
        return
    eod_report_done_for_day = today_text
    gui_log("EOD report alert sent")
    send_msg(build_eod_report_text())


def check_auto_start_bot():
    global auto_start_done_for_day

    today_text = market_day_text()
    if auto_start_done_for_day == today_text:
        return
    if not AUTO_START_BOT or running or position is not None:
        return

    now_dt = market_now()
    if not is_market_working_day(now_dt):
        return

    now_time = now_dt.time()
    if ANALYSIS_START <= now_time <= get_trade_end_time():
        auto_start_done_for_day = today_text
        gui_log("Auto start triggered for market session")
        start_bot()


def scheduler_loop():
    while True:
        try:
            check_daily_readiness_alert()
            check_auto_start_bot()
            check_morning_watchdog()
            check_eod_report_alert()
        except Exception as exc:
            gui_log(f"Scheduler error: {exc}")
        time.sleep(30)


def run_market_scan():
    global last_market_scan
    price = get_nifty_price()
    signal, trade_type, score = get_signal(price) if price else (None, "NONE", 0)
    suggestion_detail = f"{signal or 'WAIT'} {trade_type}"
    if signal and price:
        option = get_best_affordable_option(signal, price)
        if option:
            suggestion = update_trade_suggestion(signal, trade_type, score, last_confidence, "Scan tradable option found", price, option)
            suggestion_detail = (
                f"{suggestion['summary']} | SL {suggestion.get('sl', 0):.2f} | "
                f"Target {suggestion.get('target', 0):.2f}"
            )
        else:
            reason = last_option_selection_reason or f"{signal} setup found but no affordable option"
            update_trade_suggestion(None, "NONE", score, last_confidence, f"{signal} setup blocked: {reason}", price)
            suggestion_detail = f"{signal} setup blocked: {reason}"
    last_market_scan = {
        "status": "Done",
        "summary": f"NIFTY scan | Signal {signal or 'WAIT'} | Type {trade_type} | Score {score}/5",
        "results": [{"name": "NIFTY", "score": score, "detail": suggestion_detail}],
        "suggestion": last_trade_suggestion,
        "timestamp": market_now().isoformat(timespec="seconds"),
    }
    send_msg(last_market_scan["summary"] + "\n" + suggestion_detail)


def latest_backtest_day():
    day = market_now().date()
    if market_now().time() < TRADE_START:
        day -= dt.timedelta(days=1)
    while not is_market_working_day(day):
        day -= dt.timedelta(days=1)
    return day


def parse_backtest_day(value):
    text = str(value or "").strip()
    if not text:
        return latest_backtest_day()
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError("Backtest date must be YYYY-MM-DD") from exc


def parse_backtest_month(value):
    text = str(value or "").strip()
    if not text:
        day = latest_backtest_day()
        return day.replace(day=1), day
    try:
        if len(text) == 7:
            year, month = [int(part) for part in text.split("-")]
            start = dt.date(year, month, 1)
        else:
            parsed = dt.date.fromisoformat(text[:10])
            start = parsed.replace(day=1)
    except Exception as exc:
        raise ValueError("Backtest month must be YYYY-MM or YYYY-MM-DD") from exc

    if start.month == 12:
        next_month = dt.date(start.year + 1, 1, 1)
    else:
        next_month = dt.date(start.year, start.month + 1, 1)
    end = next_month - dt.timedelta(days=1)
    today = market_now().date()
    if end > today:
        end = today
    return start, end


def backtest_market_days(start_day, end_day):
    day = start_day
    while day <= end_day:
        if is_market_working_day(day):
            yield day
        day += dt.timedelta(days=1)


def fetch_backtest_candles(day):
    angel_login()
    fromdate = f"{day.strftime('%Y-%m-%d')} 09:15"
    todate = f"{day.strftime('%Y-%m-%d')} 15:30"
    data = obj.getCandleData({
        "exchange": "NSE",
        "symboltoken": NIFTY_TOKEN,
        "interval": "ONE_MINUTE",
        "fromdate": fromdate,
        "todate": todate,
    })
    if not data or data.get("status") is False:
        raise RuntimeError(f"Angel candle error: {data}")
    df = pd.DataFrame(data.get("data", []), columns=["time", "open", "high", "low", "close", "volume"])
    if df.empty:
        raise RuntimeError(f"No candles returned for {day.strftime('%Y-%m-%d')}")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["dt"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close", "volume", "dt"]).reset_index(drop=True)
    if df.empty:
        raise RuntimeError(f"No valid candles returned for {day.strftime('%Y-%m-%d')}")
    df["clock"] = df["dt"].dt.time
    df["EMA9"] = df["close"].ewm(span=9).mean()
    df["EMA21"] = df["close"].ewm(span=21).mean()
    df["VWAP"] = compute_vwap_or_session_average(df)
    df = add_supertrend(df)
    return df


def backtest_closed_signal_rows(df, index):
    """Mirror live bot timing: previous closed candles confirm, current row is entry/LTP."""
    if index < 3:
        return None, None, None
    current = df.iloc[index]
    c1 = df.iloc[index - 2]
    c2 = df.iloc[index - 1]
    return current, c1, c2


def backtest_trend_from_row(row):
    if row["EMA9"] > row["EMA21"]:
        return "UPTREND"
    if row["EMA9"] < row["EMA21"]:
        return "DOWNTREND"
    return "NEUTRAL"


def backtest_score(df, index, orb_high_value, orb_low_value, gap_day=False):
    row, c1, c2 = backtest_closed_signal_rows(df, index)
    if row is None:
        return 0, 0
    price = float(row["close"])
    trend = backtest_trend_from_row(c2)
    vwap = float(c2["VWAP"])
    ema9 = float(c2["EMA9"])
    ema21 = float(c2["EMA21"])
    supertrend_dir = str(c2.get("SUPERTREND_DIR") or "NEUTRAL")
    ce_score = 0
    pe_score = 0
    if price > vwap:
        ce_score += 1
    if supertrend_dir == "UP":
        ce_score += 1
    if ema9 > ema21 and trend == "UPTREND":
        ce_score += 1
    if not gap_day and price > (orb_high_value + ORB_BREAK_BUFFER_POINTS) and c2["close"] > orb_high_value:
        ce_score += 1
    if has_strong_two_candle_momentum(c1, c2, "CE"):
        ce_score += 1
    if price < vwap:
        pe_score += 1
    if supertrend_dir == "DOWN":
        pe_score += 1
    if ema9 < ema21 and trend == "DOWNTREND":
        pe_score += 1
    if not gap_day and price < (orb_low_value - ORB_BREAK_BUFFER_POINTS) and c2["close"] < orb_low_value:
        pe_score += 1
    if has_strong_two_candle_momentum(c1, c2, "PE"):
        pe_score += 1
    return ce_score, pe_score


def backtest_signal(df, index, orb_high_value, orb_low_value, gap_day=False):
    ce_score, pe_score = backtest_score(df, index, orb_high_value, orb_low_value, gap_day)
    row, c1, c2 = backtest_closed_signal_rows(df, index)
    if row is None:
        return None, "NONE", 0
    price = float(row["close"])
    trend = backtest_trend_from_row(c2)
    gap_direction = backtest_gap_day_direction(df) if gap_day else "FLAT"
    ce_orb_ok = (not gap_day) and price > (orb_high_value + ORB_BREAK_BUFFER_POINTS) and c2["close"] > orb_high_value
    pe_orb_ok = (not gap_day) and price < (orb_low_value - ORB_BREAK_BUFFER_POINTS) and c2["close"] < orb_low_value
    supertrend_dir = str(c2.get("SUPERTREND_DIR") or "NEUTRAL")
    ce_supertrend = (supertrend_dir == "UP") or not supertrend_filter_enabled()
    pe_supertrend = (supertrend_dir == "DOWN") or not supertrend_filter_enabled()
    ce_momentum = has_strong_two_candle_momentum(c1, c2, "CE")
    pe_momentum = has_strong_two_candle_momentum(c1, c2, "PE")
    vwap = float(c2["VWAP"])
    ema9 = float(c2["EMA9"])
    ema21 = float(c2["EMA21"])
    ce_vwap = price > vwap
    pe_vwap = price < vwap
    ce_trend = ema9 > ema21 and trend == "UPTREND"
    pe_trend = ema9 < ema21 and trend == "DOWNTREND"
    ema_gap = abs(ema9 - ema21)
    vwap_distance = abs(price - vwap)
    choppy_warning = ema_gap < MIN_EMA_GAP_POINTS and vwap_distance < MIN_VWAP_DISTANCE_POINTS
    if choppy_warning and max(ce_score, pe_score) < 4:
        return None, "NONE", max(ce_score, pe_score)

    # Live bot currently treats gap-day sustain as a warning, not a hard block.
    gap_up_pe_sustain = True
    gap_down_ce_sustain = True
    ce_half_core = ce_vwap and ce_supertrend and ce_momentum and ce_trend and gap_down_ce_sustain
    pe_half_core = pe_vwap and pe_supertrend and pe_momentum and pe_trend and gap_up_pe_sustain
    ce_full_core = (
        ce_half_core
        and (not gap_day)
        and ce_orb_ok
        and float(c2.get("close", price)) > float(c1.get("high", price))
        and price > float(c2.get("high", price))
        and not choppy_warning
    )
    pe_full_core = (
        pe_half_core
        and (not gap_day)
        and pe_orb_ok
        and float(c2.get("close", price)) < float(c1.get("low", price))
        and price < float(c2.get("low", price))
        and not choppy_warning
    )

    candidates = []
    if ce_half_core:
        timing_ok, _ = entry_timing_guard(df.iloc[: index + 1], "CE", price, vwap, ema9)
        if timing_ok:
            candidates.append(("CE", "FULL" if ce_full_core else "HALF", ce_score, 2 if ce_full_core else 1))
    if pe_half_core:
        timing_ok, _ = entry_timing_guard(df.iloc[: index + 1], "PE", price, vwap, ema9)
        if timing_ok:
            candidates.append(("PE", "FULL" if pe_full_core else "HALF", pe_score, 2 if pe_full_core else 1))

    if candidates:
        candidates.sort(key=lambda item: (item[3], item[2]), reverse=True)
        signal, trade_type, score, _ = candidates[0]
        return signal, trade_type, score
    return None, "NONE", max(ce_score, pe_score)


def estimate_backtest_premium(signal, spot_price, strike, previous_close=None):
    distance = abs(float(strike) - float(spot_price))
    base = 145 - (distance * 0.45)
    if previous_close is not None:
        base += abs(float(spot_price) - float(previous_close)) * 0.15
    return round(max(float(MIN_PREMIUM), base), 2)


def choose_backtest_option(signal, spot_price, bt_capital, previous_close=None):
    priorities = build_option_strike_priority(signal, spot_price)
    fallback = None
    for strike in priorities:
        premium = estimate_backtest_premium(signal, spot_price, strike, previous_close)
        cost = premium * FAST_LOT_SIZE
        option = {
            "symbol": f"NIFTY-EST-{int(strike)}{signal}",
            "strike": int(strike),
            "lot_size": FAST_LOT_SIZE,
            "premium": premium,
            "cost": cost,
        }
        if cost <= bt_capital:
            return option
    return fallback


def estimate_backtest_ltp(position_bt, spot_price, candle_index):
    direction_points = float(spot_price) - float(position_bt["entry_spot"])
    if position_bt["signal"] == "PE":
        direction_points = -direction_points
    minutes_held = max(0, candle_index - int(position_bt["entry_index"]))
    delta = 0.45
    decay = minutes_held * 0.035
    premium = float(position_bt["entry"]) + (direction_points * delta) - decay
    return round(max(1.0, premium), 2)


def backtest_entry_cutoff_time(trade_end_time):
    base = dt.datetime.combine(dt.date.today(), trade_end_time)
    return (base - dt.timedelta(minutes=ENTRY_CUTOFF_BUFFER_MINUTES)).time()


def backtest_sl_target_percents(day):
    if is_expiry_day(day):
        return float(EXPIRY_SL_PERCENT), float(EXPIRY_TARGET_PERCENT)
    return float(SL_PERCENT), float(TARGET_PERCENT)


def backtest_risk_cap_qty(bt_capital, qty, premium, lot_size, sl_percent):
    try:
        qty = int(qty or 0)
        premium = float(premium or 0)
        lot_size = int(lot_size or FAST_LOT_SIZE)
        sl_percent = float(sl_percent or SL_PERCENT)
    except Exception:
        return 0
    if qty <= 0 or premium <= 0 or lot_size <= 0:
        return 0
    risk_pct = max_risk_per_trade_percent()
    if risk_pct <= 0:
        return qty
    max_risk_amount = float(bt_capital or 0) * (risk_pct / 100)
    sl_amount_per_qty = premium * (sl_percent / 100)
    if max_risk_amount <= 0 or sl_amount_per_qty <= 0:
        return qty
    max_qty_by_risk = int(max_risk_amount // sl_amount_per_qty)
    risk_qty = (max_qty_by_risk // lot_size) * lot_size
    if risk_qty < lot_size:
        return 0
    return min(qty, risk_qty)


def update_backtest_trailing_sl(position_bt, ltp):
    entry = float(position_bt.get("entry", 0) or 0)
    ltp = float(ltp or 0)
    qty = int(position_bt.get("qty", 0) or 0)
    if entry <= 0 or ltp <= 0 or qty <= 0:
        return
    old_sl = float(position_bt.get("sl", 0) or 0)
    position_bt["peak"] = max(float(position_bt.get("peak", entry) or entry), ltp)
    if "initial_risk" not in position_bt:
        position_bt["initial_risk"] = abs(entry - old_sl) if old_sl > 0 else entry * (float(SL_PERCENT) / 100)
    initial_risk = max(float(position_bt.get("initial_risk") or 0), entry * 0.01)
    charges = calculate_option_charges(
        entry,
        max(entry, ltp),
        qty,
        entry_qty=position_bt.get("entry_qty", qty),
        buy_order_count=position_bt.get("entry_order_count", 1),
        sell_order_count=1,
        exchange=position_bt.get("exchange", "NFO"),
        symbol=position_bt.get("symbol", ""),
    )
    cost_lock = entry + (float(charges.get("per_qty", 0) or 0)) + (entry * (TRAIL_COST_BUFFER_PERCENT / 100))
    if ltp >= cost_lock and position_bt["sl"] < cost_lock:
        position_bt["sl"] = cost_lock
    if (ltp - entry) >= initial_risk:
        position_bt["sl"] = max(float(position_bt.get("sl", 0) or 0), cost_lock, ltp - initial_risk)


def should_backtest_early_exit(position_bt, ltp, candle_index):
    entry = float(position_bt.get("entry", 0) or 0)
    if entry <= 0:
        return False
    age_seconds = max(0, int(candle_index - int(position_bt.get("entry_index", candle_index)))) * 60
    fail_after = early_premium_fail_after_seconds()
    fail_percent = early_premium_fail_exit_percent()
    loss_percent = ((entry - float(ltp or 0)) / entry) * 100
    return fail_percent > 0 and age_seconds >= fail_after and loss_percent >= fail_percent


def backtest_qty(bt_capital, premium, trade_type, lot_size):
    max_lots = int(bt_capital // (premium * lot_size))
    if max_lots <= 0:
        return 0, 0
    used_lots = qty_lots_for_trade_type(max_lots, trade_type)
    return used_lots * lot_size, max_lots


def close_backtest_trade(position_bt, exit_price, reason, bt_capital, trades):
    gross_pnl = (float(exit_price) - float(position_bt["entry"])) * int(position_bt["qty"])
    charges = calculate_option_charges(
        position_bt["entry"],
        exit_price,
        position_bt["qty"],
        entry_qty=position_bt.get("entry_qty", position_bt["qty"]),
        buy_order_count=position_bt.get("entry_order_count", 1),
        sell_order_count=1,
        exchange=position_bt.get("exchange", "NFO"),
        symbol=position_bt.get("symbol", ""),
    )
    net_pnl = gross_pnl - charges["total"]
    bt_capital += net_pnl
    trades.append({
        "time": position_bt["entry_time"],
        "exit_time": position_bt["exit_time"],
        "type": position_bt["trade_type"],
        "signal": position_bt["signal"],
        "symbol": position_bt["symbol"],
        "entry": round(float(position_bt["entry"]), 2),
        "exit": round(float(exit_price), 2),
        "qty": int(position_bt["qty"]),
        "gross_pnl": round(float(gross_pnl), 2),
        "charges": charges["total"],
        "buy_charges": charges.get("buy_charges", charges.get("buy_total", 0)),
        "sell_charges": charges.get("sell_charges", charges.get("sell_total", 0)),
        "net_pnl": round(float(net_pnl), 2),
        "pnl": round(float(net_pnl), 2),
        "reason": reason,
    })
    return bt_capital


def build_mobile_backtest_report(mode, day, df, start_capital, final_capital, trades, stop_reason):
    pnl_total = final_capital - start_capital
    gross_total = sum(float(trade.get("gross_pnl", trade.get("pnl", 0)) or 0) for trade in trades)
    charges_total = sum(float(trade.get("charges", 0) or 0) for trade in trades)
    wins = sum(1 for trade in trades if trade["pnl"] > 0)
    losses = sum(1 for trade in trades if trade["pnl"] <= 0)
    win_rate = (wins / len(trades) * 100) if trades else 0
    ret = (pnl_total / start_capital * 100) if start_capital else 0
    lines = [
        "MOBILE BACKTEST REPORT",
        f"Mode: {mode}",
        "Strategy Source: Live paper bot mirror",
        "Signal Source: Angel historic NIFTY candles using previous closed-candle confirmation",
        "Premium Source: Phone fast option estimate (real option P&L can still differ from live LTP)",
        f"Date: {day.strftime('%Y-%m-%d')}",
        f"Start Capital: {start_capital:.2f}",
        f"Final Capital: {final_capital:.2f}",
        f"Gross P&L: {gross_total:.2f}",
        f"Charges: {charges_total:.2f}",
        f"Net P&L: {pnl_total:.2f}",
        f"Return: {ret:.2f}%",
        f"Candles: {len(df)}",
        f"Trades: {len(trades)}",
        f"Wins: {wins}",
        f"Losses: {losses}",
        f"Win Rate: {win_rate:.2f}%",
    ]
    if stop_reason:
        lines.append(f"Stop Reason: {stop_reason}")
    lines.extend(["", "TRADES"])
    if trades:
        for trade in trades[-25:]:
            lines.append(
                f"{trade['time']} -> {trade['exit_time']} | {trade.get('type', '')} | {trade['signal']} | {trade['symbol']} | "
                f"Entry {trade['entry']:.2f} | Exit {trade['exit']:.2f} | Qty {trade['qty']} | "
                f"Gross {trade.get('gross_pnl', trade['pnl']):.2f} | Charges {trade.get('charges', 0):.2f} | "
                f"Net {trade['pnl']:.2f} | {trade['reason']}"
            )
    else:
        lines.append("No closed trade")
    summary = (
        f"{mode} {day.strftime('%Y-%m-%d')} | Trades {len(trades)} | "
        f"P&L {pnl_total:.2f} | Return {ret:.2f}%"
    )
    return summary, "\n".join(lines)


def run_mobile_backtest_day(mode, day, start_capital):
    bt_capital = start_capital
    df = fetch_backtest_candles(day)
    if len(df) < 30:
        raise RuntimeError(f"Not enough candles for {day.strftime('%Y-%m-%d')}")
    orb_block = df[(df["clock"] >= ORB_START) & (df["clock"] < ORB_END)]
    if orb_block.empty:
        orb_block = df.head(5)
    bt_orb_high = float(orb_block["high"].max())
    bt_orb_low = float(orb_block["low"].min())
    bt_gap_day = backtest_gap_day_mode(df, day)
    trade_end_time = EXPIRY_TRADE_END if is_expiry_day(day) else TRADE_END
    bt_entry_cutoff = backtest_entry_cutoff_time(trade_end_time)
    sl_percent, target_percent = backtest_sl_target_percents(day)
    position_bt = None
    trades = []
    stop_reason = ""
    profit_floor = None
    profit_lock_level = 0.0

    for index in range(21, len(df)):
        row = df.iloc[index]
        now_clock = row["clock"]
        if now_clock < TRADE_START:
            continue
        if now_clock > trade_end_time:
            break

        if position_bt is not None:
            ltp = estimate_backtest_ltp(position_bt, row["close"], index)
            position_bt["ltp"] = ltp
            position_bt["exit_time"] = row["dt"].strftime("%H:%M:%S")
            update_backtest_trailing_sl(position_bt, ltp)
            if should_backtest_early_exit(position_bt, ltp, index):
                bt_capital = close_backtest_trade(position_bt, ltp, "BT EARLY PREMIUM FAIL", bt_capital, trades)
                position_bt = None
            elif ltp <= position_bt["sl"]:
                bt_capital = close_backtest_trade(position_bt, ltp, "BT SL/TRAIL HIT", bt_capital, trades)
                position_bt = None
            elif ltp >= position_bt["target"]:
                bt_capital = close_backtest_trade(position_bt, ltp, "BT TARGET", bt_capital, trades)
                position_bt = None

        live_equity = bt_capital
        if position_bt is not None:
            gross_open = (position_bt["ltp"] - position_bt["entry"]) * position_bt["qty"]
            open_charges = calculate_option_charges(
                position_bt["entry"],
                position_bt["ltp"],
                position_bt["qty"],
                entry_qty=position_bt.get("entry_qty", position_bt["qty"]),
                buy_order_count=position_bt.get("entry_order_count", 1),
                sell_order_count=1,
                exchange=position_bt.get("exchange", "NFO"),
                symbol=position_bt.get("symbol", ""),
            )
            live_equity += gross_open - open_charges["total"]
        if live_equity <= start_capital * (1 - MAX_DAILY_LOSS):
            if position_bt is not None:
                bt_capital = close_backtest_trade(position_bt, position_bt["ltp"], "BT DAILY LOSS", bt_capital, trades)
                position_bt = None
            stop_reason = f"Stopped: daily loss limit hit ({MAX_DAILY_LOSS * 100:.1f}%)"
            break
        profit_lock_level, profit_floor, lock_changed = backtest_profit_lock_update(
            start_capital, live_equity, profit_lock_level, profit_floor
        )
        if not lock_changed and profit_floor is not None and live_equity < profit_floor:
            if position_bt is not None:
                bt_capital = close_backtest_trade(position_bt, position_bt["ltp"], "BT PROFIT FLOOR", bt_capital, trades)
                position_bt = None
            stop_reason = "Stopped: profit floor protected"
            break

        if position_bt is None:
            if now_clock >= bt_entry_cutoff:
                continue
            signal, trade_type, score = backtest_signal(df, index, bt_orb_high, bt_orb_low, bt_gap_day)
            if not signal:
                continue
            previous_close = df.iloc[index - 1]["close"]
            option = choose_backtest_option(signal, row["close"], bt_capital, previous_close)
            if option is None:
                continue
            qty, max_lots = backtest_qty(bt_capital, option["premium"], trade_type, FAST_LOT_SIZE)
            qty = backtest_risk_cap_qty(bt_capital, qty, option["premium"], FAST_LOT_SIZE, sl_percent)
            if qty <= 0:
                continue
            position_bt = {
                "signal": signal,
                "trade_type": trade_type,
                "symbol": option["symbol"],
                "entry": option["premium"],
                "entry_spot": float(row["close"]),
                "entry_time": row["dt"].strftime("%H:%M:%S"),
                "entry_index": index,
                "ltp": option["premium"],
                "qty": qty,
                "entry_qty": qty,
                "entry_order_count": 1,
                "planned_full_qty": max_lots * FAST_LOT_SIZE,
                "sl": option["premium"] * (1 - sl_percent / 100),
                "target": option["premium"] * (1 + target_percent / 100),
                "peak": option["premium"],
                "initial_risk": option["premium"] * (sl_percent / 100),
                "exit_time": row["dt"].strftime("%H:%M:%S"),
                "score": score,
            }

    if position_bt is not None:
        last_row = df.iloc[min(len(df) - 1, index)]
        ltp = estimate_backtest_ltp(position_bt, last_row["close"], min(len(df) - 1, index))
        position_bt["exit_time"] = last_row["dt"].strftime("%H:%M:%S")
        bt_capital = close_backtest_trade(position_bt, ltp, "BT EOD EXIT", bt_capital, trades)

    summary, report = build_mobile_backtest_report(mode, day, df, start_capital, bt_capital, trades, stop_reason)
    return {
        "day": day,
        "summary": summary,
        "report": report,
        "start_capital": start_capital,
        "final_capital": bt_capital,
        "trades": trades,
        "stop_reason": stop_reason,
        "candles": len(df),
    }


def build_monthly_backtest_report(mode, start_day, end_day, start_capital, final_capital, day_results, skipped):
    all_trades = []
    for result in day_results:
        all_trades.extend(result.get("trades", []))
    pnl_total = final_capital - start_capital
    gross_total = sum(float(trade.get("gross_pnl", trade.get("pnl", 0)) or 0) for trade in all_trades)
    charges_total = sum(float(trade.get("charges", 0) or 0) for trade in all_trades)
    wins = sum(1 for trade in all_trades if float(trade.get("pnl", 0) or 0) > 0)
    losses = sum(1 for trade in all_trades if float(trade.get("pnl", 0) or 0) <= 0)
    win_rate = (wins / len(all_trades) * 100) if all_trades else 0
    ret = (pnl_total / start_capital * 100) if start_capital else 0
    lines = [
        "MONTHLY BACKTEST REPORT",
        f"Mode: {mode}",
        "Strategy Source: Live paper bot mirror",
        "Signal Source: Angel historic NIFTY candles using previous closed-candle confirmation",
        "Premium Source: Phone fast option estimate (real option P&L can still differ from live LTP)",
        f"From: {start_day.strftime('%Y-%m-%d')} To: {end_day.strftime('%Y-%m-%d')}",
        f"Start Capital: {start_capital:.2f}",
        f"Final Capital: {final_capital:.2f}",
        f"Gross P&L: {gross_total:.2f}",
        f"Charges: {charges_total:.2f}",
        f"Net P&L: {pnl_total:.2f}",
        f"Return: {ret:.2f}%",
        f"Tested Days: {len(day_results)}",
        f"Skipped Days: {len(skipped)}",
        f"Trades: {len(all_trades)}",
        f"Wins: {wins}",
        f"Losses: {losses}",
        f"Win Rate: {win_rate:.2f}%",
    ]
    if skipped:
        lines.extend(["", "SKIPPED"])
        for day, reason in skipped[-10:]:
            lines.append(f"{day.strftime('%Y-%m-%d')} | {reason}")
    lines.extend(["", "DAY SUMMARY"])
    for result in day_results[-25:]:
        day_pnl = float(result["final_capital"]) - float(result["start_capital"])
        lines.append(
            f"{result['day'].strftime('%Y-%m-%d')} | Trades {len(result.get('trades', []))} | "
            f"P&L {day_pnl:.2f} | Final {float(result['final_capital']):.2f}"
        )
    lines.extend(["", "LAST TRADES"])
    if all_trades:
        for trade in all_trades[-25:]:
            lines.append(
                f"{trade['time']} -> {trade['exit_time']} | {trade.get('type', '')} | {trade['signal']} | {trade['symbol']} | "
                f"Entry {trade['entry']:.2f} | Exit {trade['exit']:.2f} | Qty {trade['qty']} | "
                f"Gross {trade.get('gross_pnl', trade['pnl']):.2f} | Charges {trade.get('charges', 0):.2f} | "
                f"Net {trade['pnl']:.2f} | {trade['reason']}"
            )
    else:
        lines.append("No closed trade")
    summary = (
        f"{mode} {start_day.strftime('%Y-%m')} | Days {len(day_results)} | Trades {len(all_trades)} | "
        f"P&L {pnl_total:.2f} | Return {ret:.2f}%"
    )
    return summary, "\n".join(lines)


def run_mobile_monthly_backtest(payload, mode, start_capital):
    start_day, end_day = parse_backtest_month(payload.get("month") or payload.get("date"))
    running_capital = start_capital
    day_results = []
    skipped = []
    for day in backtest_market_days(start_day, end_day):
        try:
            result = run_mobile_backtest_day(mode, day, running_capital)
            running_capital = float(result["final_capital"])
            day_results.append(result)
        except Exception as exc:
            skipped.append((day, str(exc)[:160]))
    if not day_results and skipped:
        raise RuntimeError("Monthly backtest skipped all days: " + skipped[-1][1])
    return build_monthly_backtest_report(mode, start_day, end_day, start_capital, running_capital, day_results, skipped)


def run_mobile_backtest(payload=None):
    payload = payload or {}
    mode = str(payload.get("mode", "FAST") or "FAST").upper()
    start_capital = float(payload.get("capital") or paper_capital or capital)
    if mode in {"MONTH", "MONTHLY"}:
        return run_mobile_monthly_backtest(payload, "MONTHLY", start_capital)
    day = parse_backtest_day(payload.get("date"))
    result = run_mobile_backtest_day(mode, day, start_capital)
    return result["summary"], result["report"]


def run_mobile_backtest_worker(payload=None):
    global last_backtest_report, last_backtest_summary, backtest_running
    try:
        summary, report = run_mobile_backtest(payload)
        last_backtest_summary = summary
        last_backtest_report = report
        gui_log(f"Backtest done | {summary}")
        send_msg(f"Backtest done\n{summary}")
    except Exception as exc:
        last_backtest_summary = "Backtest error"
        last_backtest_report = f"Backtest error: {exc}"
        gui_log(f"Backtest error: {exc}")
        send_msg(f"Backtest error: {exc}")
    finally:
        with backtest_lock:
            backtest_running = False


def start_mobile_backtest(payload=None):
    global last_backtest_report, last_backtest_summary, backtest_running
    with backtest_lock:
        if backtest_running:
            return "backtest already running"
        backtest_running = True
    mode = str((payload or {}).get("mode", "FAST") or "FAST").upper()
    last_backtest_summary = f"{mode} backtest running..."
    last_backtest_report = "Backtest running. Refresh after a few seconds."
    threading.Thread(target=run_mobile_backtest_worker, args=(payload or {},), daemon=True).start()
    gui_log(f"{mode} backtest started")
    return "backtest started"


def refresh_master_cache_worker():
    global master_cache
    try:
        master_cache = None
        get_master()
        gui_log("Master cache refreshed")
    except Exception as exc:
        gui_log(f"Master cache refresh failed: {exc}")


def server_update_worker(force=False):
    try:
        result = check_server_update(force=force, source="manual")
        gui_log("Server update check: " + str(result.get("summary", result)))
    except Exception as exc:
        gui_log(f"Server update check failed: {exc}")


def health_test_worker():
    try:
        text = "OPTION KING AI MANUAL HEALTH CHECK\n\n" + build_health_text(test_angel=True)
        sent = send_msg(text)
        gui_log("Health alert queued" if sent else "Health built but Telegram missing")
    except Exception as exc:
        gui_log(f"Health test failed: {exc}")


def trade_buy_sell_charges(trade):
    total = float(trade.get("charges", 0) or 0)
    buy = float(trade.get("buy_charges", 0) or 0)
    sell = float(trade.get("sell_charges", 0) or 0)
    if total and not (buy or sell):
        buy = total / 2
        sell = total / 2
    if not total:
        total = buy + sell
    return buy, sell, total


def build_recent_order_rows(limit=40):
    rows = []
    for trade in trade_history[-int(limit or 40):]:
        buy_charges, sell_charges, total_charges = trade_buy_sell_charges(trade)
        qty = int(float(trade.get("qty", 0) or 0))
        entry = float(trade.get("entry", 0) or 0)
        exit_price = float(trade.get("exit", 0) or 0)
        gross_pnl = float(trade.get("gross_pnl", trade.get("pnl", 0)) or 0)
        net_pnl = float(trade.get("net_pnl", trade.get("pnl", 0)) or 0)
        common = {
            "trade_id": trade.get("trade_id", ""),
            "date": trade.get("date", ""),
            "mode": trade.get("mode", "PAPER"),
            "trade_type": trade.get("type", trade.get("trade_type", "")),
            "signal": trade.get("signal", ""),
            "symbol": trade.get("symbol", ""),
            "qty": qty,
        }
        rows.append({
            **common,
            "time": trade.get("time", ""),
            "event": "BUY",
            "side": "PURCHASE",
            "price": entry,
            "turnover": entry * qty,
            "charges": buy_charges,
            "gross_pnl": 0.0,
            "net_pnl": -buy_charges,
            "reason": "Purchase entry",
        })
        rows.append({
            **common,
            "time": trade.get("exit_time", ""),
            "event": "SELL",
            "side": "SALE",
            "price": exit_price,
            "turnover": exit_price * qty,
            "charges": sell_charges,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "total_charges": total_charges,
            "reason": trade.get("reason", ""),
        })
    return rows[-int(limit or 40):]


def get_position_payload():
    if not position:
        return None
    return {
        "signal": position.get("signal"),
        "trade_type": position.get("trade_type"),
        "symbol": position.get("option", {}).get("symbol", "DEMO"),
        "entry": position.get("entry"),
        "ltp": position.get("ltp"),
        "qty": position.get("qty"),
        "sl": position.get("sl"),
        "target": position.get("target"),
    }


def empty_chart_payload(message):
    return {
        "timestamp": market_now().isoformat(timespec="seconds"),
        "labels": [],
        "timestamps": [],
        "open": [],
        "high": [],
        "low": [],
        "close": [],
        "ema9": [],
        "ema21": [],
        "vwap": [],
        "supertrend": [],
        "supertrend_dir": [],
        "volume": [],
        "message": message,
    }


def build_chart_payload_from_df(df, message="OK", candle_limit=None):
    if df is None or df.empty:
        return empty_chart_payload("Waiting for candle data")
    data = df.copy()
    for col in ["open", "high", "low", "close", "volume"]:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna(subset=["open", "high", "low", "close"])
    if data.empty:
        return empty_chart_payload("Waiting for valid candle data")
    if "EMA9" not in data.columns:
        data["EMA9"] = data["close"].ewm(span=9).mean()
    if "EMA21" not in data.columns:
        data["EMA21"] = data["close"].ewm(span=21).mean()
    if "VWAP" not in data.columns:
        data["VWAP"] = compute_vwap_or_session_average(data)
    if "SUPERTREND" not in data.columns or "SUPERTREND_DIR" not in data.columns:
        data = add_supertrend(data)
    try:
        limit = int(candle_limit or config.get("chart_candle_limit", 240) or 240)
    except Exception:
        limit = 240
    limit = max(20, min(limit, 375))
    last = data.tail(limit)
    labels = []
    timestamps = []
    for value in last["time"].astype(str).tolist():
        try:
            parsed = pd.to_datetime(value)
            labels.append(parsed.strftime("%d %b %H:%M"))
            timestamps.append(value)
        except Exception:
            labels.append(value[-16:] if len(value) >= 16 else value)
            timestamps.append(value)
    return {
        "timestamp": market_now().isoformat(timespec="seconds"),
        "labels": labels,
        "timestamps": timestamps,
        "open": [round(float(v), 2) for v in last["open"].tolist()],
        "high": [round(float(v), 2) for v in last["high"].tolist()],
        "low": [round(float(v), 2) for v in last["low"].tolist()],
        "close": [round(float(v), 2) for v in last["close"].tolist()],
        "ema9": [round(float(v), 2) for v in last["EMA9"].tolist()],
        "ema21": [round(float(v), 2) for v in last["EMA21"].tolist()],
        "vwap": [round(float(v), 2) for v in last["VWAP"].tolist()],
        "supertrend": [None if pd.isna(v) else round(float(v), 2) for v in last["SUPERTREND"].tolist()],
        "supertrend_dir": [str(v or "NEUTRAL") for v in last["SUPERTREND_DIR"].tolist()],
        "volume": [round(float(v), 2) for v in last["volume"].tolist()],
        "message": message,
    }


def status_chart_payload():
    """Build chart from already cached candles only; never call Angel API from /status."""
    global last_status_chart
    try:
        if last_candle_df is None or last_candle_df.empty:
            return last_status_chart or empty_chart_payload("Chart refresh pending")
        last_status_chart = build_chart_payload_from_df(last_candle_df, "Cached live chart", candle_limit=120)
        return last_status_chart
    except Exception as exc:
        return last_status_chart or empty_chart_payload(f"Chart cache unavailable: {exc}")


def status_payload():
    health = health_payload(test_angel=False)
    chart = status_chart_payload()
    return {
        "app": "Option King AI Cloud",
        "server_version": SERVER_VERSION,
        "update_status": last_update_status,
        "running": running,
        "mode": "PAPER",
        "capital": capital,
        "paper_capital": paper_capital,
        "daily_pnl": daily_pnl,
        "live_equity": get_live_equity(),
        "trades_taken": trades_taken,
        "max_trades": "Unlimited",
        "confidence": last_confidence,
        "score": last_score,
        "signal": last_signal,
        "trend": last_trend,
        "supertrend": last_supertrend,
        "reentry_block_summary": reentry_blocks_summary(),
        "nifty": last_nifty_price,
        "position": get_position_payload(),
        "recent_orders": build_recent_order_rows(20),
        "suggestion": last_trade_suggestion,
        "suggestion_summary": last_trade_suggestion.get("summary", "Suggestion: --"),
        "last_option_selection_reason": last_option_selection_reason,
        "backtest_summary": last_backtest_summary,
        "backtest_running": backtest_running,
        "health": health,
        "health_summary": health.get("summary", last_health_summary),
        "health_status": health.get("status", "--"),
        "chart": chart,
        "chart_count": len(chart.get("close") or []),
        "chart_message": chart.get("message", "--"),
        "market_session": get_market_session_status()[1],
        "market_open": get_market_session_status()[0],
        "market_timezone": MARKET_TIMEZONE,
        "expiry_day": is_expiry_day(),
        "normal_trade_end": TRADE_END.strftime("%H:%M"),
        "expiry_trade_end": EXPIRY_TRADE_END.strftime("%H:%M"),
        "trade_end": get_trade_end_time().strftime("%H:%M"),
        "timestamp": market_now().isoformat(timespec="seconds"),
    }


def chart_payload():
    global last_status_chart
    df = get_indicators()
    if df is None or df.empty:
        raw_df = get_candles()
        if raw_df is None or raw_df.empty:
            return {
                "timestamp": market_now().isoformat(timespec="seconds"),
                "labels": [],
                "close": [],
                "ema9": [],
                "ema21": [],
                "vwap": [],
                "supertrend": [],
                "supertrend_dir": [],
                "message": "Waiting for candle data",
            }
        raw_df = raw_df.copy()
        for col in ["open", "high", "low", "close", "volume"]:
            raw_df[col] = pd.to_numeric(raw_df[col], errors="coerce")
        raw_df = raw_df.dropna(subset=["close"])
        if raw_df.empty:
            return {
                "timestamp": market_now().isoformat(timespec="seconds"),
                "labels": [],
                "close": [],
                "ema9": [],
                "ema21": [],
                "vwap": [],
                "supertrend": [],
                "supertrend_dir": [],
                "message": "Waiting for valid candle data",
            }
        raw_df["EMA9"] = raw_df["close"].ewm(span=9).mean()
        raw_df["EMA21"] = raw_df["close"].ewm(span=21).mean()
        raw_df["VWAP"] = compute_vwap_or_session_average(raw_df)
        raw_df = add_supertrend(raw_df)
        df = raw_df

    try:
        candle_limit = int(config.get("chart_candle_limit", 240) or 240)
    except Exception:
        candle_limit = 240
    candle_limit = max(60, min(candle_limit, 375))
    last = df.tail(candle_limit)
    labels = []
    timestamps = []
    for value in last["time"].astype(str).tolist():
        try:
            parsed = pd.to_datetime(value)
            labels.append(parsed.strftime("%d %b %H:%M"))
            timestamps.append(value)
        except Exception:
            labels.append(value[-16:] if len(value) >= 16 else value)
            timestamps.append(value)

    payload = {
        "timestamp": market_now().isoformat(timespec="seconds"),
        "labels": labels,
        "timestamps": timestamps,
        "open": [round(float(v), 2) for v in last["open"].tolist()],
        "high": [round(float(v), 2) for v in last["high"].tolist()],
        "low": [round(float(v), 2) for v in last["low"].tolist()],
        "close": [round(float(v), 2) for v in last["close"].tolist()],
        "ema9": [round(float(v), 2) for v in last["EMA9"].tolist()],
        "ema21": [round(float(v), 2) for v in last["EMA21"].tolist()],
        "vwap": [round(float(v), 2) for v in last["VWAP"].tolist()],
        "supertrend": [None if pd.isna(v) else round(float(v), 2) for v in last["SUPERTREND"].tolist()],
        "supertrend_dir": [str(v or "NEUTRAL") for v in last["SUPERTREND_DIR"].tolist()],
        "volume": [round(float(v), 2) for v in last["volume"].tolist()],
        "message": "OK",
    }
    last_status_chart = payload
    return payload


def build_live_text():
    pos = get_position_payload()
    pos_text = "No open position" if not pos else json.dumps(pos, indent=2)
    return "\n".join([
        "LIVE BOT STATUS",
        "",
        f"Running: {'YES' if running else 'NO'}",
        f"Capital: {capital:.2f}",
        f"Live Equity: {get_live_equity():.2f}",
        f"NIFTY: {last_nifty_price if last_nifty_price else '--'}",
        f"Signal: {last_signal}",
        f"Score: {last_score}/5",
        f"Supertrend: {last_supertrend}",
        f"Suggestion: {last_trade_suggestion.get('summary', '--')}",
        "",
        "POSITION",
        pos_text,
        "",
        "RECENT LOGS",
        *(logs[-25:] or ["No logs yet."]),
    ])


def build_risk_text():
    floor_text = f"{daily_profit_floor:.2f}" if daily_profit_floor else "OFF"
    return "\n".join([
        "RISK MONITOR",
        "",
        f"Start Capital: {paper_capital:.2f}",
        f"Current Capital: {capital:.2f}",
        f"Live Equity: {get_live_equity():.2f}",
        f"Daily P&L: {daily_pnl:.2f}",
        "",
        f"Market Session: {get_market_session_status()[1]}",
        f"Market Timezone: {MARKET_TIMEZONE}",
        f"Auto Start Bot: {'ON' if AUTO_START_BOT else 'OFF'}",
        f"Readiness Alert: {READINESS_ALERT_TIME.strftime('%H:%M')}",
        f"Morning Watchdog: {MORNING_WATCHDOG_READY_TIME.strftime('%H:%M')} ready, {MORNING_WATCHDOG_START_CHECK_TIME.strftime('%H:%M')} rescue, {MORNING_WATCHDOG_FINAL_CHECK_TIME.strftime('%H:%M')} confirm",
        f"EOD Report Alert: {EOD_REPORT_TIME.strftime('%H:%M')}",
        f"Analysis Start: {ANALYSIS_START.strftime('%H:%M')}",
        f"Trade Start: {TRADE_START.strftime('%H:%M')}",
        f"Normal Trade End: {TRADE_END.strftime('%H:%M')}",
        f"Expiry Trade End: {EXPIRY_TRADE_END.strftime('%H:%M')}",
        f"Entry Cutoff: {entry_cutoff_time().strftime('%H:%M')}",
        f"EOD Force Exit: {eod_exit_time().strftime('%H:%M')}",
        "",
        f"Daily Loss Limit: {MAX_DAILY_LOSS * 100:.2f}%",
        f"Profit Lock Ladder: {profit_lock_levels_text()}",
        f"Active Profit Floor: {floor_text}",
        f"Active Profit Lock: {daily_profit_lock_level * 100:.0f}%" if daily_profit_lock_level else "Active Profit Lock: OFF",
        "Loss Streak Stop: OFF (daily loss limit controls risk)",
        f"Re-entry Block: {reentry_blocks_summary()}",
        f"SL: {SL_PERCENT:.2f}%",
        f"Target: {TARGET_PERCENT:.2f}%",
        f"Expiry SL: {EXPIRY_SL_PERCENT:.2f}%",
        f"Expiry Target: {EXPIRY_TARGET_PERCENT:.2f}%",
        "Trade Type: FULL / HALF / NONE",
        "HALF Rule: VWAP + Supertrend + strong candle momentum + EMA",
        "FULL Rule: HALF rule + ORB + continuation breakout",
        "Gap Day: ORB OFF; FULL disabled, HALF/risk-capped only",
        "Gap-up PE: requires VWAP sustain + EMA down + Supertrend down",
        "Gap-down CE: requires VWAP sustain + EMA up + Supertrend up",
        f"Half Qty: {half_trade_qty_percent():.0f}% of affordable lots",
        "Score Order: 1 VWAP, 2 Supertrend, 3 EMA, 4 ORB (normal only), 5 Candle",
        f"Reversal Exit: after {reversal_min_hold_seconds() / 60:.0f}m or {reversal_min_loss_percent():.1f}% option loss, {reversal_confirm_candles()} candle confirm",
        f"Supertrend Filter: {'ON' if supertrend_filter_enabled() else 'OFF'}",
        f"Supertrend: ATR {int(config.get('supertrend_period', SUPERTREND_PERIOD))} x {float(config.get('supertrend_multiplier', SUPERTREND_MULTIPLIER)):.2f}",
        "",
        "Charges: ON" if charges_enabled() else "Charges: OFF",
        f"Brokerage: {charge_value('brokerage_per_order', BROKERAGE_PER_ORDER):.2f} per executed order",
        f"NSE Options Txn: {charge_value('option_transaction_rate_nse', OPTION_TRANSACTION_RATE_NSE) * 100:.5f}%",
        f"STT Sell: {charge_value('option_stt_sell_rate', OPTION_STT_SELL_RATE) * 100:.4f}%",
    ])


def build_reports_text():
    total_pnl = sum(float(trade.get("pnl", 0) or 0) for trade in trade_history)
    gross_pnl = sum(float(trade.get("gross_pnl", trade.get("pnl", 0)) or 0) for trade in trade_history)
    total_charges = sum(float(trade.get("charges", 0) or 0) for trade in trade_history)
    wins = sum(1 for trade in trade_history if float(trade.get("pnl", 0) or 0) > 0)
    losses = sum(1 for trade in trade_history if float(trade.get("pnl", 0) or 0) <= 0)
    lines = [
        "OPTION KING AI CLOUD REPORTS",
        "",
        f"Closed Trades: {len(trade_history)}",
        f"Wins: {wins}",
        f"Losses: {losses}",
        f"Gross P&L: {gross_pnl:.2f}",
        f"Charges: {total_charges:.2f}",
        f"Net P&L: {total_pnl:.2f}",
        "",
        "ALL CLOSED TRADES",
    ]
    for trade in trade_history:
        lines.append(
            f"{trade.get('date')} {trade.get('time')}->{trade.get('exit_time')} | {trade.get('signal')} | "
            f"{trade.get('symbol')} | Qty {trade.get('qty')} | Gross {float(trade.get('gross_pnl', trade.get('pnl', 0)) or 0):.2f} | "
            f"Charges {float(trade.get('charges', 0) or 0):.2f} | Net {float(trade.get('pnl', 0) or 0):.2f} | {trade.get('reason')}"
        )
    if not trade_history:
        lines.append("No closed trades yet.")
    return "\n".join(lines)


def build_settings_text():
    return "\n".join([
        "CLOUD SETTINGS",
        "",
        f"Angel API Key: {'SET' if config.get('api_key') else 'MISSING'}",
        f"Client ID: {'SET' if config.get('client_id') else 'MISSING'}",
        f"TOTP Secret: {'SET' if config.get('totp_secret') else 'MISSING'}",
        f"Telegram: {'SET' if config.get('telegram_token') and config.get('chat_id') else 'MISSING'}",
        f"API Token: {'SET' if api_token() else 'MISSING'}",
        f"Market Timezone: {MARKET_TIMEZONE}",
        f"Expiry Today: {'YES' if is_expiry_day() else 'NO'}",
        f"Trade End Today: {get_trade_end_time().strftime('%H:%M')}",
        f"Entry Cutoff Today: {entry_cutoff_time().strftime('%H:%M')}",
        f"EOD Force Exit Today: {eod_exit_time().strftime('%H:%M')}",
        f"Morning Watchdog: {MORNING_WATCHDOG_READY_TIME.strftime('%H:%M')} ready, {MORNING_WATCHDOG_START_CHECK_TIME.strftime('%H:%M')} rescue, {MORNING_WATCHDOG_FINAL_CHECK_TIME.strftime('%H:%M')} confirm",
        f"Re-entry Block: {reentry_blocks_summary()}",
        f"Start Capital: {paper_capital:.2f}",
        f"Profit Lock Ladder: {profit_lock_levels_text()}",
        f"Expiry Weekdays: {config.get('expiry_weekdays', [1])}",
        "Trade Type: FULL / HALF / NONE",
        "HALF Rule: VWAP + Supertrend + strong candle momentum + EMA",
        "FULL Rule: HALF rule + ORB + continuation breakout",
        "Gap Day: ORB OFF; FULL disabled, HALF/risk-capped only",
        "Gap-up PE: requires VWAP sustain + EMA down + Supertrend down",
        "Gap-down CE: requires VWAP sustain + EMA up + Supertrend up",
        f"Half Qty: {half_trade_qty_percent():.0f}% of affordable lots",
        "Score Order: 1 VWAP, 2 Supertrend, 3 EMA, 4 ORB (normal only), 5 Candle",
        f"Reversal Exit: after {reversal_min_hold_seconds() / 60:.0f}m or {reversal_min_loss_percent():.1f}% option loss, {reversal_confirm_candles()} candle confirm",
        f"Supertrend Filter: {'ON' if supertrend_filter_enabled() else 'OFF'}",
        f"Supertrend Period: {int(config.get('supertrend_period', SUPERTREND_PERIOD))}",
        f"Supertrend Multiplier: {float(config.get('supertrend_multiplier', SUPERTREND_MULTIPLIER)):.2f}",
        f"Charges Enabled: {'YES' if charges_enabled() else 'NO'}",
        f"Brokerage Per Order: {charge_value('brokerage_per_order', BROKERAGE_PER_ORDER):.2f}",
        f"NSE Options Transaction: {charge_value('option_transaction_rate_nse', OPTION_TRANSACTION_RATE_NSE) * 100:.5f}%",
        f"Options STT Sell: {charge_value('option_stt_sell_rate', OPTION_STT_SELL_RATE) * 100:.4f}%",
        f"Server Version: {SERVER_VERSION}",
        f"Mobile App Latest: {mobile_app_update_payload().get('latest_version')}",
        f"Mobile App URL: {mobile_app_update_payload().get('apk_url')}",
        f"Auto Update: {'ON' if config.get('auto_update_enabled', True) else 'OFF'}",
        f"Update Status: {last_update_status.get('summary', '--')}",
        f"Health: {last_health_summary}",
        "",
        "Update Manifest URLs:",
        *update_manifest_urls(),
        "",
        f"Data Folder: {DATA_DIR}",
        f"Trade Folder: {TRADE_DIR}",
        f"Cache Folder: {CACHE_DIR}",
    ])


def json_safe(value):
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except Exception:
            pass
    try:
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return None
    except Exception:
        pass
    return str(value)


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload, status=200):
        try:
            body = json.dumps(json_safe(payload), ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Api-Token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except OSError as exc:
            if getattr(exc, "errno", None) in {32, 103, 104}:
                return
            raise

    def authorized(self):
        return self.headers.get("X-Api-Token", "") == api_token()

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_OPTIONS(self):
        self.send_json({"ok": True})

    def do_GET(self):
        if not self.authorized():
            self.send_json({"ok": False, "error": "unauthorized"}, 401)
            return
        path = urlparse(self.path).path
        if path == "/status":
            self.send_json({"ok": True, "data": status_payload()})
        elif path == "/chart":
            self.send_json({"ok": True, "data": chart_payload()})
        elif path == "/trades":
            orders = build_recent_order_rows(80)
            self.send_json({
                "ok": True,
                "count": len(trade_history),
                "order_count": len(orders),
                "data": trade_history,
                "orders": orders,
                "recent_orders": orders,
            })
        elif path == "/logs":
            self.send_json({"ok": True, "data": logs[-100:]})
        elif path == "/scan":
            self.send_json({"ok": True, "data": last_market_scan})
        elif path == "/backtest":
            self.send_json({"ok": True, "summary": last_backtest_summary, "report": last_backtest_report})
        elif path == "/live":
            self.send_json({"ok": True, "title": "Live Bot", "text": build_live_text()})
        elif path == "/risk":
            self.send_json({"ok": True, "title": "Risk Monitor", "text": build_risk_text()})
        elif path == "/reports":
            self.send_json({"ok": True, "title": "Reports", "text": build_reports_text(), "count": len(trade_history), "trades": trade_history})
        elif path == "/settings-info":
            self.send_json({"ok": True, "title": "Settings", "text": build_settings_text()})
        elif path == "/health":
            self.send_json({"ok": True, "title": "Health", "data": health_payload(), "text": build_health_text()})
        elif path == "/update-status":
            self.send_json({"ok": True, "data": last_update_status})
        elif path == "/mobile-app-update":
            self.send_json({"ok": True, "data": mobile_app_update_payload()})
        else:
            self.send_json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        if not self.authorized():
            self.send_json({"ok": False, "error": "unauthorized"}, 401)
            return
        path = urlparse(self.path).path
        body = self.read_body()
        if path == "/start":
            start_bot()
            self.send_json({"ok": True, "message": "start requested"})
        elif path == "/stop":
            stop_bot()
            self.send_json({"ok": True, "message": "stop requested"})
        elif path == "/capital":
            update_capital(float(body.get("capital", 0)))
            self.send_json({"ok": True, "message": "capital updated"})
        elif path == "/close-position":
            if position is not None:
                close_position(position.get("ltp", position.get("entry", 0)), "MOBILE CLOSE")
            self.send_json({"ok": True, "message": "close position requested"})
        elif path == "/scan":
            threading.Thread(target=run_market_scan, daemon=True).start()
            self.send_json({"ok": True, "message": "scan started"})
        elif path == "/backtest":
            message = start_mobile_backtest(body)
            self.send_json({"ok": True, "message": message})
        elif path == "/master-cache":
            threading.Thread(target=refresh_master_cache_worker, daemon=True).start()
            self.send_json({"ok": True, "message": "master cache refresh started"})
        elif path == "/telegram-config":
            try:
                update_telegram_config(body.get("telegram_token", ""), body.get("chat_id", ""))
                sent = send_msg("Option King AI phone server: Telegram connected", wait=True)
                self.send_json({"ok": True, "message": "telegram settings saved" if sent else "telegram saved but test send failed"})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
        elif path == "/telegram-test":
            if send_msg("Option King AI phone server: Telegram test alert", wait=True):
                self.send_json({"ok": True, "message": "telegram test sent"})
            else:
                self.send_json({"ok": False, "error": "telegram token/chat_id missing or send failed"}, 400)
        elif path == "/health-test":
            threading.Thread(target=health_test_worker, daemon=True).start()
            self.send_json({"ok": True, "message": "health alert started"})
        elif path == "/server-update":
            threading.Thread(target=server_update_worker, args=(bool(body.get("force")),), daemon=True).start()
            self.send_json({"ok": True, "message": "server update check started", "data": last_update_status})
        elif path == "/mobile-app-update":
            changed = False
            for source_key, config_key in [
                ("version", "mobile_app_version"),
                ("apk_url", "mobile_app_update_url"),
                ("release_notes", "mobile_app_release_notes"),
            ]:
                if body.get(source_key):
                    config[config_key] = str(body.get(source_key)).strip()
                    changed = True
            if changed:
                config["mobile_app_updated_at"] = market_now().isoformat(timespec="seconds")
                save_cloud_config()
            self.send_json({"ok": True, "message": "mobile app update info saved" if changed else "mobile app update info unchanged", "data": mobile_app_update_payload()})
        else:
            self.send_json({"ok": False, "error": "not found"}, 404)

    def log_message(self, _format, *_args):
        return


def main():
    global server
    load_config()
    load_trade_history_from_disk()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    threading.Thread(target=auto_update_loop, daemon=True).start()
    host = config.get("host", "0.0.0.0")
    port = int(config.get("port", 8765))
    server = ThreadingHTTPServer((host, port), Handler)
    gui_log(f"Cloud API server started: http://{host}:{port}")
    server.serve_forever()



# ===== OPTION KING AI PATCH: ROUND-TRIP CHARGES + 5% COST TRAIL =====
# Version: 2026.05.09-roundtrip-cost-trail-1

TRAIL_COST_BUFFER_PERCENT = 5.0


def _okai_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _okai_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


def okai_round_trip_charges(entry_price, exit_price, qty, exchange="NSE"):
    """Buy + sell charges for long option paper trades."""
    entry_price = _okai_float(entry_price)
    exit_price = _okai_float(exit_price)
    qty = _okai_int(qty)
    if entry_price <= 0 or exit_price <= 0 or qty <= 0:
        return {
            "total": 0.0,
            "per_qty": 0.0,
            "buy_total": 0.0,
            "sell_total": 0.0,
            "gst": 0.0,
            "debug": "Charges skipped: invalid entry/exit/qty",
        }

    buy_turnover = entry_price * qty
    sell_turnover = exit_price * qty
    total_turnover = buy_turnover + sell_turnover

    brokerage_per_order = _okai_float(config.get("brokerage_per_order", globals().get("BROKERAGE_PER_ORDER", 20.0)))
    txn_rate = _okai_float(config.get("option_transaction_rate_nse", globals().get("OPTION_TRANSACTION_RATE_NSE", 0.0003552)))
    stt_sell_rate = _okai_float(config.get("option_stt_sell_rate", globals().get("OPTION_STT_SELL_RATE", 0.0015)))
    stamp_buy_rate = _okai_float(config.get("option_stamp_buy_rate", globals().get("OPTION_STAMP_BUY_RATE", 0.00003)))
    sebi_rate = _okai_float(config.get("sebi_charge_rate", globals().get("SEBI_CHARGE_RATE", 10 / 10000000)))
    ipft_rate = _okai_float(config.get("ipft_charge_rate", globals().get("IPFT_CHARGE_RATE", 0.000000001)))
    gst_rate = _okai_float(config.get("gst_rate", globals().get("GST_RATE", 0.18)))

    buy_brokerage = brokerage_per_order
    sell_brokerage = brokerage_per_order
    buy_txn = buy_turnover * txn_rate
    sell_txn = sell_turnover * txn_rate
    buy_sebi = buy_turnover * sebi_rate
    sell_sebi = sell_turnover * sebi_rate
    buy_ipft = buy_turnover * ipft_rate
    sell_ipft = sell_turnover * ipft_rate
    stamp = buy_turnover * stamp_buy_rate
    stt = sell_turnover * stt_sell_rate
    buy_gst = (buy_brokerage + buy_txn + buy_sebi) * gst_rate
    sell_gst = (sell_brokerage + sell_txn + sell_sebi) * gst_rate
    gst = buy_gst + sell_gst

    buy_total = buy_brokerage + buy_txn + buy_sebi + buy_ipft + stamp
    sell_total = sell_brokerage + sell_txn + sell_sebi + sell_ipft + stt
    buy_charges = buy_total + buy_gst
    sell_charges = sell_total + sell_gst
    total = buy_charges + sell_charges
    per_qty = total / qty

    return {
        "total": total,
        "per_qty": per_qty,
        "buy_total": buy_total,
        "sell_total": sell_total,
        "buy_charges": buy_charges,
        "sell_charges": sell_charges,
        "buy_gst": buy_gst,
        "sell_gst": sell_gst,
        "brokerage": buy_brokerage + sell_brokerage,
        "transaction": buy_txn + sell_txn,
        "stt": stt,
        "stamp": stamp,
        "sebi": buy_sebi + sell_sebi,
        "ipft": buy_ipft + sell_ipft,
        "gst": gst,
        "buy_turnover": buy_turnover,
        "sell_turnover": sell_turnover,
        "debug": (
            f"Round-trip charges | Buy {buy_charges:.2f} + Sell {sell_charges:.2f} "
            f"= {total:.2f} | GST included {gst:.2f} | Per qty {per_qty:.2f}"
        ),
    }


def okai_charge_adjusted_cost_lock(entry_price, ltp, qty):
    entry_price = _okai_float(entry_price)
    ltp = _okai_float(ltp)
    charges = okai_round_trip_charges(entry_price, max(entry_price, ltp), qty)
    buffer_amount = entry_price * (TRAIL_COST_BUFFER_PERCENT / 100)
    cost_lock = entry_price + charges["per_qty"] + buffer_amount
    return cost_lock, charges, buffer_amount


def calculate_option_charges(
    entry_price,
    exit_price,
    qty,
    entry_qty=None,
    buy_order_count=1,
    sell_order_count=1,
    exchange="NSE",
    symbol="",
    **kwargs,
):
    return okai_round_trip_charges(entry_price, exit_price, qty, exchange)


def calculate_trade_charges(entry_price, exit_price, qty, exchange="NSE", **kwargs):
    return okai_round_trip_charges(entry_price, exit_price, qty, exchange)


def estimate_option_charges(entry_price, exit_price, qty, exchange="NSE", **kwargs):
    return okai_round_trip_charges(entry_price, exit_price, qty, exchange)


def update_trailing_sl(*args, **kwargs):
    """Charge-adjusted trailing SL. CE and PE are both long option premium trades."""
    global position
    if position is None:
        return

    entry = _okai_float(position.get("entry"))
    ltp = _okai_float(position.get("ltp", entry))
    old_sl = _okai_float(position.get("sl"))
    qty = _okai_int(position.get("qty"))

    if entry <= 0 or ltp <= 0 or qty <= 0:
        return

    if "initial_risk" not in position:
        position["initial_risk"] = abs(entry - old_sl) if old_sl > 0 else entry * (_okai_float(globals().get("SL_PERCENT", 20)) / 100)
    initial_risk = max(_okai_float(position.get("initial_risk")), entry * 0.01)

    cost_lock, charges, buffer_amount = okai_charge_adjusted_cost_lock(entry, ltp, qty)

    if ltp >= cost_lock and position["sl"] < cost_lock:
        position["sl"] = cost_lock
        gui_log(
            f"SL moved to cost+charges+5% | Entry {entry:.2f} | "
            f"Charges/Qty {charges['per_qty']:.2f} | Buffer {buffer_amount:.2f} | "
            f"SL {old_sl:.2f}->{position['sl']:.2f}"
        )

    profit = ltp - entry
    if profit >= initial_risk:
        trail_sl = max(position["sl"], cost_lock, ltp - initial_risk)
        if trail_sl > position["sl"]:
            old = position["sl"]
            position["sl"] = trail_sl
            gui_log(
                f"Trailing SL active after 1R | {position.get('signal', '')} | "
                f"Risk {initial_risk:.2f} | SL {old:.2f}->{position['sl']:.2f}"
            )

# ===== END PATCH =====


# ===== OPTION KING AI PATCH: MAX ORDER QTY CAP =====
# Version: 2026.05.09-max-order-qty-cap-1

MAX_ORDER_QTY = 87750


def cap_qty_to_order_limit(qty, lot_size, source="LIVE"):
    try:
        qty = int(qty or 0)
        lot_size = int(lot_size or FAST_LOT_SIZE)
    except Exception:
        return 0, False
    max_qty = int(config.get("max_order_qty", MAX_ORDER_QTY) or MAX_ORDER_QTY)
    capped_raw = min(qty, max_qty)
    capped_qty = (capped_raw // lot_size) * lot_size
    capped = capped_qty != qty
    if capped:
        try:
            gui_log(
                f"Qty capped by max order limit | {source} | Requested {qty} | "
                f"Limit {max_qty} | Lot {lot_size} | Final {capped_qty}"
            )
        except Exception:
            pass
    return max(0, capped_qty), capped


_OKAI_ORIGINAL_GET_QTY = get_qty


def get_qty(premium, trade_type, lot_size):
    qty = _OKAI_ORIGINAL_GET_QTY(premium, trade_type, lot_size)
    capped_qty, _ = cap_qty_to_order_limit(qty, lot_size, "TRADE")
    return capped_qty


# ===== OPTION KING AI PATCH: RISK-SIZED QTY =====
# Version: 2026.05.14-risk-sized-qty-1

_OKAI_ORDER_CAP_GET_QTY = get_qty


def max_risk_per_trade_percent():
    try:
        return max(0.0, float(config.get("max_risk_per_trade_percent", MAX_RISK_PER_TRADE_PERCENT)))
    except Exception:
        return float(MAX_RISK_PER_TRADE_PERCENT)


def active_sl_percent():
    try:
        return float(EXPIRY_SL_PERCENT if is_expiry_day() else SL_PERCENT)
    except Exception:
        return float(SL_PERCENT)


def risk_limited_qty(qty, premium, lot_size, source="TRADE"):
    try:
        qty = int(qty or 0)
        premium = float(premium or 0)
        lot_size = int(lot_size or FAST_LOT_SIZE)
    except Exception:
        return 0
    if qty <= 0 or premium <= 0 or lot_size <= 0:
        return 0

    risk_pct = max_risk_per_trade_percent()
    if risk_pct <= 0:
        return qty

    base_capital = max(float(capital or 0), float(paper_capital or 0))
    max_risk_amount = base_capital * (risk_pct / 100)
    sl_amount_per_qty = premium * (active_sl_percent() / 100)
    if max_risk_amount <= 0 or sl_amount_per_qty <= 0:
        return qty

    max_qty_by_risk = int(max_risk_amount // sl_amount_per_qty)
    risk_qty = (max_qty_by_risk // lot_size) * lot_size
    if risk_qty < lot_size:
        needed = (sl_amount_per_qty * lot_size) / (risk_pct / 100) if risk_pct else 0
        gui_log(
            f"Trade blocked by risk cap | {source} | Premium {premium:.2f} | "
            f"Lot {lot_size} | Risk cap {risk_pct:.1f}% | Need capital approx {needed:.0f}"
        )
        return 0

    final_qty = min(qty, risk_qty)
    if final_qty < qty:
        gui_log(
            f"Qty risk-capped | {source} | Requested {qty} | Final {final_qty} | "
            f"Premium {premium:.2f} | SL {active_sl_percent():.1f}% | Max risk {risk_pct:.1f}%"
        )
    return final_qty


def get_qty(premium, trade_type, lot_size):
    qty = _OKAI_ORDER_CAP_GET_QTY(premium, trade_type, lot_size)
    return risk_limited_qty(qty, premium, lot_size, "TRADE")


_OKAI_ORIGINAL_BACKTEST_QTY = backtest_qty


def backtest_qty(bt_capital, premium, trade_type, lot_size):
    qty, max_lots = _OKAI_ORIGINAL_BACKTEST_QTY(bt_capital, premium, trade_type, lot_size)
    capped_qty, capped = cap_qty_to_order_limit(qty, lot_size, "BACKTEST")
    if capped:
        max_lots = capped_qty // int(lot_size or FAST_LOT_SIZE)
    return capped_qty, max_lots

# ===== END PATCH =====


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


# ===== OPTION KING AI PATCH: ANGEL SESSION + TOKEN GUARD =====
# Version: 2026.05.13-angel-session-guard-1

SERVER_VERSION = "2026.05.16-live-backtest-capital-1"

try:
    ThreadingHTTPServer.allow_reuse_address = True
except Exception:
    pass

ANGEL_SESSION_MAX_AGE_SECONDS = 6 * 60 * 60
ANGEL_RELOGIN_MIN_GAP_SECONDS = 15
_angel_login_lock = threading.Lock()
_angel_login_time = 0.0
_angel_login_day = None
_angel_last_relogin_attempt = 0.0
_angel_last_guard_log = {}

_OKAI_SESSION_BASE_ANGEL_LOGIN = angel_login


def _okai_throttled_guard_log(key, message, interval=30):
    now_ts = time.time()
    last_ts = float(_angel_last_guard_log.get(key, 0) or 0)
    if now_ts - last_ts >= interval:
        _angel_last_guard_log[key] = now_ts
        gui_log(message)


def _okai_payload_text(payload):
    try:
        return str(payload)
    except Exception:
        return repr(payload)


def _okai_is_invalid_token_payload(payload):
    text = _okai_payload_text(payload).lower()
    return (
        "invalid token" in text
        or "ag8001" in text
        or "jwt" in text and "invalid" in text
        or "session" in text and ("expired" in text or "invalid" in text)
    )


def _okai_current_market_day_text():
    try:
        return market_day_text()
    except Exception:
        try:
            return market_now().strftime("%Y-%m-%d")
        except Exception:
            return dt.datetime.now().strftime("%Y-%m-%d")


def angel_login(force=False, reason=""):
    """Refresh stale Angel sessions instead of reusing yesterday's token."""
    global obj, _angel_login_time, _angel_login_day, _angel_last_relogin_attempt

    now_ts = time.time()
    today_text = _okai_current_market_day_text()
    max_age = int(config.get("angel_session_max_age_seconds", ANGEL_SESSION_MAX_AGE_SECONDS) or ANGEL_SESSION_MAX_AGE_SECONDS)

    session_age_ok = bool(_angel_login_time and (now_ts - _angel_login_time) < max_age)
    session_day_ok = (_angel_login_day == today_text)
    if obj is not None and not force and session_age_ok and session_day_ok:
        return

    with _angel_login_lock:
        now_ts = time.time()
        session_age_ok = bool(_angel_login_time and (now_ts - _angel_login_time) < max_age)
        session_day_ok = (_angel_login_day == today_text)
        if obj is not None and not force and session_age_ok and session_day_ok:
            return

        if now_ts - _angel_last_relogin_attempt < ANGEL_RELOGIN_MIN_GAP_SECONDS and obj is None:
            return

        _angel_last_relogin_attempt = now_ts
        if force or obj is not None:
            obj = None
            why = reason or "session refresh"
            _okai_throttled_guard_log("angel_relogin", f"Angel session refresh: {why}", 20)

        _OKAI_SESSION_BASE_ANGEL_LOGIN()
        _angel_login_time = time.time()
        _angel_login_day = today_text


def get_ltp(exchange, symbol, token):
    """LTP fetch with invalid-token auto re-login and low-noise logs."""
    global obj
    token = str(token)

    for attempt in range(3):
        try:
            angel_login()
            data = obj.ltpData(exchange, symbol, token)

            if _okai_is_invalid_token_payload(data):
                _okai_throttled_guard_log(
                    "ltp_invalid_token",
                    f"LTP token/session refresh needed for {symbol} {token}; re-login once.",
                    20,
                )
                angel_login(force=True, reason=f"LTP invalid token {symbol} {token}")
                continue

            if not isinstance(data, dict):
                raise RuntimeError(f"Invalid LTP response type {type(data).__name__}: {_okai_payload_text(data)[:120]}")

            if data.get("status") is False or data.get("success") is False:
                raise RuntimeError(f"Angel LTP rejected: {_okai_payload_text(data)[:180]}")

            payload = data.get("data")
            if not isinstance(payload, dict):
                raise RuntimeError(f"Invalid LTP payload: {_okai_payload_text(data)[:180]}")

            ltp = payload.get("ltp")
            if ltp is None:
                raise RuntimeError(f"LTP missing: {_okai_payload_text(data)[:180]}")
            return float(ltp)

        except Exception as exc:
            text = str(exc)
            if _okai_is_invalid_token_payload(text):
                angel_login(force=True, reason=f"LTP exception {symbol} {token}")
                continue
            _okai_throttled_guard_log("ltp_wait", f"LTP wait {symbol} {token}: {text[:160]}", 20)
            time.sleep(1)
    return None


def get_nifty_price():
    """Use the live quote token first; the 99926000 token is mainly for historic candles."""
    price = get_ltp("NSE", "NIFTY", NIFTY_TOKEN_FALLBACK)
    if price is None:
        price = get_ltp("NSE", NIFTY_SYMBOL, NIFTY_TOKEN)
    return price


def get_candles():
    """Candle fetch with session refresh, cache fallback, and no repeated bad-payload spam."""
    global last_candle_df, last_candle_fetch_time, candle_rate_limited_until

    try:
        session_open, session_reason = _okai_market_fetch_allowed()
        if not session_open:
            _okai_throttled_guard_log("candle_market_closed", f"Candle fetch skipped: {session_reason}", 300)
            return None
    except Exception:
        pass

    now_ts = time.time()
    if last_candle_df is not None and now_ts - last_candle_fetch_time < CANDLE_CACHE_SECONDS:
        return last_candle_df.copy()
    if candle_rate_limited_until > now_ts and last_candle_df is not None:
        return last_candle_df.copy()

    params = {
        "exchange": "NSE",
        "symboltoken": NIFTY_TOKEN,
        "interval": "ONE_MINUTE",
        "fromdate": market_now().strftime("%Y-%m-%d 09:15"),
        "todate": market_now().strftime("%Y-%m-%d %H:%M"),
    }

    for attempt in range(3):
        try:
            angel_login()
            data = obj.getCandleData(params)

            if _okai_is_invalid_token_payload(data):
                _okai_throttled_guard_log("candle_invalid_token", "Candle token/session expired; re-login once.", 20)
                angel_login(force=True, reason="candle invalid token")
                continue

            if not isinstance(data, dict):
                msg = f"Invalid candle response type {type(data).__name__}: {_okai_payload_text(data)[:120]}"
                _okai_throttled_guard_log("candle_bad_response", f"Candle data wait: {msg}", 30)
                return last_candle_df.copy() if last_candle_df is not None else None

            if data.get("status") is False or data.get("success") is False:
                text = _okai_payload_text(data)
                if _okai_is_invalid_token_payload(text):
                    angel_login(force=True, reason="candle rejected invalid token")
                    continue
                raise RuntimeError(text[:220])

            rows = data.get("data", [])
            if rows is None or rows == "":
                _okai_throttled_guard_log("candle_empty", "Candle data wait: Angel returned empty candle data.", 30)
                return last_candle_df.copy() if last_candle_df is not None else None
            if not isinstance(rows, list):
                _okai_throttled_guard_log(
                    "candle_bad_payload",
                    f"Candle data wait: Invalid candle payload type {type(rows).__name__}.",
                    30,
                )
                return last_candle_df.copy() if last_candle_df is not None else None
            if rows and not isinstance(rows[0], (list, tuple)):
                _okai_throttled_guard_log("candle_bad_row", f"Candle data wait: Invalid candle row {str(rows[0])[:120]}", 30)
                return last_candle_df.copy() if last_candle_df is not None else None

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
            if _okai_is_invalid_token_payload(msg):
                angel_login(force=True, reason="candle exception invalid token")
                continue
            if "access rate" in lower or "access denied" in lower or "too many" in lower:
                candle_rate_limited_until = now_ts + CANDLE_RATE_LIMIT_COOLDOWN
            _okai_throttled_guard_log("candle_wait", f"Candle data wait: {msg[:180]}", 30)
            time.sleep(1)

    return last_candle_df.copy() if last_candle_df is not None else None

# ===== END PATCH =====


# ===== OPTION KING AI PATCH: EARLY BAD-ENTRY EXIT =====
# Version: 2026.05.14-risk-sized-qty-1

_OKAI_RISK_BASE_MANAGE_PAPER_TRADE = manage_paper_trade


def early_premium_fail_exit_percent():
    try:
        return max(0.0, float(config.get("early_premium_fail_exit_percent", EARLY_PREMIUM_FAIL_EXIT_PERCENT)))
    except Exception:
        return float(EARLY_PREMIUM_FAIL_EXIT_PERCENT)


def early_premium_fail_after_seconds():
    try:
        return max(0.0, float(config.get("early_premium_fail_after_seconds", EARLY_PREMIUM_FAIL_AFTER_SECONDS)))
    except Exception:
        return float(EARLY_PREMIUM_FAIL_AFTER_SECONDS)


def should_exit_on_early_premium_fail():
    if position is None:
        return False, ""
    age = position_age_seconds()
    loss_percent = position_loss_percent()
    fail_after = early_premium_fail_after_seconds()
    fail_percent = early_premium_fail_exit_percent()
    if fail_percent <= 0 or age < fail_after or loss_percent < fail_percent:
        return False, ""
    return True, f"EARLY EXIT: premium failed {loss_percent:.1f}% after {int(age)}s"


def manage_paper_trade(premium, current_price=None):
    if position is None:
        return
    position["ltp"] = premium
    early_exit, early_reason = should_exit_on_early_premium_fail()
    if early_exit:
        close_position(premium, early_reason)
        return
    _OKAI_RISK_BASE_MANAGE_PAPER_TRADE(premium, current_price)


# ===== OPTION KING AI PATCH: REALISTIC OPTION-CANDLE BACKTEST =====
# Version: 2026.05.16-realistic-option-backtest-1

SERVER_VERSION = "2026.05.16-realistic-option-backtest-1"

REALISTIC_BACKTEST_MODES = {"REAL", "REALISTIC", "PRO", "REALISTIC_DAY"}
REALISTIC_MONTHLY_MODES = {"REAL_MONTHLY", "REALISTIC_MONTHLY", "MONTHLY_REAL", "MONTHLY_REALISTIC"}
REALISTIC_OPTION_CACHE_DIR = os.path.join(CACHE_DIR, "real_option_candles")


def realistic_backtest_mode(mode):
    return str(mode or "").upper() in REALISTIC_BACKTEST_MODES


def realistic_monthly_backtest_mode(mode):
    return str(mode or "").upper() in REALISTIC_MONTHLY_MODES


def bt_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def realistic_slippage_percent():
    return max(0.0, bt_float(config.get("backtest_slippage_percent", 0.12), 0.12))


def realistic_spread_percent():
    return max(0.0, bt_float(config.get("backtest_bid_ask_spread_percent", 0.18), 0.18))


def realistic_liquidity_impact_percent():
    return max(0.0, bt_float(config.get("backtest_liquidity_impact_percent", 0.08), 0.08))


def realistic_max_liquidity_impact_percent():
    return max(0.0, bt_float(config.get("backtest_max_liquidity_impact_percent", 1.50), 1.50))


def realistic_option_cache_path(exchange, token, day):
    ensure_dirs()
    os.makedirs(REALISTIC_OPTION_CACHE_DIR, exist_ok=True)
    safe_exchange = str(exchange or "NFO").replace("/", "_")
    safe_token = str(token or "").replace("/", "_")
    return os.path.join(REALISTIC_OPTION_CACHE_DIR, f"{safe_exchange}_{safe_token}_{day.strftime('%Y%m%d')}.json")


def normalize_historic_candle_rows(rows, label):
    if rows is None or rows == "":
        raise RuntimeError(f"{label}: no candle rows")
    if not isinstance(rows, list):
        raise RuntimeError(f"{label}: invalid candle payload type {type(rows).__name__}")
    if rows and not isinstance(rows[0], (list, tuple)):
        raise RuntimeError(f"{label}: invalid candle row {str(rows[0])[:120]}")
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    if df.empty:
        raise RuntimeError(f"{label}: empty candle dataframe")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    parsed = pd.to_datetime(df["time"], errors="coerce")
    try:
        if getattr(parsed.dt, "tz", None) is not None:
            parsed = parsed.dt.tz_convert(ZoneInfo(MARKET_TIMEZONE)).dt.tz_localize(None)
    except Exception:
        try:
            parsed = parsed.dt.tz_localize(None)
        except Exception:
            pass
    df["dt"] = parsed
    df = df.dropna(subset=["open", "high", "low", "close", "volume", "dt"]).copy()
    if df.empty:
        raise RuntimeError(f"{label}: no valid numeric candle rows")
    df = df.sort_values("dt").reset_index(drop=True)
    df["clock"] = df["dt"].dt.time
    return df


def fetch_real_historic_candles(exchange, token, day, symbol="", interval="ONE_MINUTE"):
    exchange = str(exchange or "NFO")
    token = str(token or "")
    if not token:
        raise RuntimeError("Option token missing")
    cache_path = realistic_option_cache_path(exchange, token, day)
    label = f"{symbol or token} {day.strftime('%Y-%m-%d')}"
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as file:
            rows = json.load(file)
        return normalize_historic_candle_rows(rows, label)

    angel_login()
    params = {
        "exchange": exchange,
        "symboltoken": token,
        "interval": interval,
        "fromdate": f"{day.strftime('%Y-%m-%d')} 09:15",
        "todate": f"{day.strftime('%Y-%m-%d')} 15:30",
    }
    data = obj.getCandleData(params)
    if not isinstance(data, dict) or data.get("status") is False or data.get("success") is False:
        raise RuntimeError(f"{label}: Angel candle error {str(data)[:220]}")
    rows = data.get("data", [])
    df = normalize_historic_candle_rows(rows, label)
    with open(cache_path, "w", encoding="utf-8") as file:
        json.dump(rows, file)
    return df


def realistic_option_contracts(signal, spot_price, day):
    master = get_master()
    df = master[
        (master["name"] == "NIFTY")
        & (master["exch_seg"] == "NFO")
        & (master["instrumenttype"].str.contains("OPT", na=False))
        & (master["symbol"].str.endswith(signal))
    ].copy()
    if df.empty:
        return []
    df["expiry_dt"] = parse_expiry_series(df["expiry"])
    df["strike_num"] = pd.to_numeric(df["strike"], errors="coerce") / 100
    df = df.dropna(subset=["expiry_dt", "strike_num"])
    df = df[df["expiry_dt"].dt.date >= day]
    df = df.sort_values(["expiry_dt", "strike_num"])
    contracts = []
    for strike in build_option_strike_priority(signal, spot_price):
        temp = df[df["strike_num"] == int(strike)]
        if temp.empty:
            continue
        row = temp.iloc[0]
        contracts.append({
            "symbol": str(row["symbol"]),
            "token": str(row["token"]),
            "exchange": str(row["exch_seg"]),
            "strike": int(strike),
            "lot_size": int(float(row.get("lotsize", FAST_LOT_SIZE) or FAST_LOT_SIZE)),
            "expiry": str(row.get("expiry", "")),
        })
    return contracts


def option_candle_at_or_after(option_df, when_dt, max_delay_minutes=2):
    if option_df is None or option_df.empty:
        return None, None
    rows = option_df[option_df["dt"] >= when_dt]
    if rows.empty:
        return None, None
    idx = int(rows.index[0])
    row = option_df.loc[idx]
    delay = (row["dt"] - when_dt).total_seconds() / 60
    if delay > max_delay_minutes:
        return None, None
    return row, idx


def option_candle_for_time(option_df, when_dt):
    if option_df is None or option_df.empty:
        return None, None
    same = option_df[option_df["dt"] == when_dt]
    if not same.empty:
        idx = int(same.index[0])
        return option_df.loc[idx], idx
    return option_candle_at_or_after(option_df, when_dt, max_delay_minutes=1)


def realistic_execution_price(raw_price, candle, side, qty, lot_size):
    raw_price = max(0.05, bt_float(raw_price, 0))
    qty = max(0, int(qty or 0))
    lot_size = max(1, int(lot_size or FAST_LOT_SIZE))
    volume = max(0.0, bt_float(candle.get("volume", 0), 0)) if candle is not None else 0.0
    spread = realistic_spread_percent()
    slippage = realistic_slippage_percent()
    liquidity = 0.0
    if volume > 0 and qty > 0:
        liquidity = min(realistic_max_liquidity_impact_percent(), (qty / max(volume, lot_size)) * realistic_liquidity_impact_percent())
    elif qty > 0:
        liquidity = realistic_max_liquidity_impact_percent()
    total_pct = spread + slippage + liquidity
    adjustment = raw_price * (total_pct / 100)
    if str(side).upper() == "BUY":
        fill = raw_price + adjustment
    else:
        fill = max(0.05, raw_price - adjustment)
    return round(fill, 2), {
        "raw": round(raw_price, 2),
        "fill": round(fill, 2),
        "spread_pct": round(spread, 4),
        "slippage_pct": round(slippage, 4),
        "liquidity_pct": round(liquidity, 4),
        "total_pct": round(total_pct, 4),
        "volume": round(volume, 2),
    }


def realistic_block_key(signal, option):
    return f"{signal}:{int(option.get('strike', 0) or 0)}"


def realistic_block_reason(signal, option, now_dt, blocks, trade_type="HALF"):
    if blocks.get("post_exit_until") and now_dt < blocks["post_exit_until"]:
        return "post-exit wait active"
    direction_until = blocks.get("direction", {}).get(signal)
    if direction_until and now_dt < direction_until and normalize_trade_type(trade_type) != "FULL":
        return f"{signal} direction cooldown"
    symbol_until = blocks.get("symbol", {}).get(option.get("symbol", ""))
    if symbol_until and now_dt < symbol_until:
        return f"{option.get('symbol')} cooldown"
    strike_until = blocks.get("strike", {}).get(realistic_block_key(signal, option))
    if strike_until and now_dt < strike_until:
        return f"{signal} strike cooldown"
    return ""


def realistic_register_exit_block(position_bt, reason, net_pnl, exit_dt, blocks):
    wait_minutes = post_exit_wait_minutes()
    if wait_minutes > 0:
        blocks["post_exit_until"] = max(blocks.get("post_exit_until") or exit_dt, exit_dt + dt.timedelta(minutes=wait_minutes))
    reason_text = str(reason or "").upper()
    should_block = float(net_pnl or 0) < 0 or any(text in reason_text for text in REENTRY_BLOCK_REASONS)
    if not should_block:
        return
    until_dt = exit_dt + dt.timedelta(minutes=reentry_block_minutes())
    signal = position_bt.get("signal", "")
    symbol = position_bt.get("symbol", "")
    strike_key = realistic_block_key(signal, position_bt.get("option") or {})
    if signal:
        blocks.setdefault("direction", {})[signal] = until_dt
    if symbol:
        blocks.setdefault("symbol", {})[symbol] = until_dt
    if strike_key:
        blocks.setdefault("strike", {})[strike_key] = until_dt


def choose_realistic_backtest_option(signal, spot_price, bt_capital, day, entry_dt, trade_type, blocks):
    notes = []
    for option in realistic_option_contracts(signal, spot_price, day):
        block = realistic_block_reason(signal, option, entry_dt, blocks, trade_type)
        if block:
            notes.append(f"{option['symbol']} blocked: {block}")
            continue
        try:
            option_df = fetch_real_historic_candles(option["exchange"], option["token"], day, option["symbol"])
            entry_row, entry_option_index = option_candle_at_or_after(option_df, entry_dt)
        except Exception as exc:
            notes.append(f"{option['symbol']} candle missing: {str(exc)[:90]}")
            continue
        if entry_row is None:
            notes.append(f"{option['symbol']} no entry candle near {entry_dt.strftime('%H:%M')}")
            continue
        raw_entry = float(entry_row["close"])
        if raw_entry < MIN_PREMIUM:
            notes.append(f"{option['symbol']} premium {raw_entry:.2f} below min {MIN_PREMIUM:.2f}")
            continue
        lot_size = int(option.get("lot_size") or FAST_LOT_SIZE)
        qty, max_lots = backtest_qty(bt_capital, raw_entry, trade_type, lot_size)
        if qty <= 0:
            notes.append(f"{option['symbol']} not affordable at {raw_entry:.2f}")
            continue
        entry_price, exec_info = realistic_execution_price(raw_entry, entry_row, "BUY", qty, lot_size)
        qty, max_lots = backtest_qty(bt_capital, entry_price, trade_type, lot_size)
        if qty <= 0:
            notes.append(f"{option['symbol']} not affordable after execution cost {entry_price:.2f}")
            continue
        entry_price, exec_info = realistic_execution_price(raw_entry, entry_row, "BUY", qty, lot_size)
        option.update({
            "premium": entry_price,
            "raw_premium": raw_entry,
            "cost": entry_price * lot_size,
            "option_df": option_df,
            "entry_option_index": entry_option_index,
            "entry_candle": entry_row.to_dict(),
            "entry_execution": exec_info,
            "max_lots": max_lots,
        })
        return option, notes
    return None, notes


def realistic_update_trailing(position_bt, raw_ltp, candle_dt, source, detail_logs):
    old_sl = float(position_bt.get("sl", 0) or 0)
    update_backtest_trailing_sl(position_bt, raw_ltp)
    new_sl = float(position_bt.get("sl", 0) or 0)
    if new_sl > old_sl:
        text = f"{candle_dt.strftime('%H:%M:%S')} trail {old_sl:.2f}->{new_sl:.2f} using {source} {raw_ltp:.2f}"
        position_bt.setdefault("trail_log", []).append(text)
        detail_logs.append(text)


def realistic_sell_fill(raw_exit, candle, qty, lot_size):
    return realistic_execution_price(raw_exit, candle, "SELL", qty, lot_size)


def realistic_intrabar_exit(position_bt, candle, detail_logs):
    candle_dt = candle["dt"]
    lot_size = int(position_bt.get("lot_size") or FAST_LOT_SIZE)
    qty = int(position_bt.get("qty") or 0)
    path = ["open", "low", "high", "close"] if float(candle["close"]) >= float(candle["open"]) else ["open", "high", "low", "close"]
    path_note = "green path open-low-high-close" if path[1] == "low" else "red path open-high-low-close"

    for point in path:
        raw_price = float(candle[point])
        if point in {"open", "high"} and raw_price >= float(position_bt["target"]):
            raw_exit = raw_price if point == "open" and raw_price > float(position_bt["target"]) else float(position_bt["target"])
            fill, exec_info = realistic_sell_fill(raw_exit, candle, qty, lot_size)
            return fill, f"BT TARGET intrabar ({path_note})", exec_info, raw_exit
        if point in {"open", "low"} and raw_price <= float(position_bt["sl"]):
            raw_exit = raw_price if point == "open" and raw_price < float(position_bt["sl"]) else float(position_bt["sl"])
            fill, exec_info = realistic_sell_fill(raw_exit, candle, qty, lot_size)
            return fill, f"BT SL/TRAIL intrabar ({path_note})", exec_info, raw_exit
        if point == "high":
            realistic_update_trailing(position_bt, raw_price, candle_dt, "option high", detail_logs)
            if raw_price >= float(position_bt["target"]):
                fill, exec_info = realistic_sell_fill(float(position_bt["target"]), candle, qty, lot_size)
                return fill, f"BT TARGET intrabar after trail ({path_note})", exec_info, float(position_bt["target"])
        if point == "close":
            position_bt["ltp"] = raw_price
            realistic_update_trailing(position_bt, raw_price, candle_dt, "option close", detail_logs)

    if should_backtest_early_exit(position_bt, float(candle["close"]), int(position_bt.get("current_index", 0))):
        fill, exec_info = realistic_sell_fill(float(candle["close"]), candle, qty, lot_size)
        return fill, "BT EARLY PREMIUM FAIL", exec_info, float(candle["close"])
    return None, "", None, None


def close_realistic_backtest_trade(position_bt, exit_price, reason, bt_capital, trades, exit_candle, exit_exec, raw_exit, blocks, detail_logs):
    gross_pnl = (float(exit_price) - float(position_bt["entry"])) * int(position_bt["qty"])
    charges = calculate_option_charges(
        position_bt["entry"],
        exit_price,
        position_bt["qty"],
        entry_qty=position_bt.get("entry_qty", position_bt["qty"]),
        buy_order_count=position_bt.get("entry_order_count", 1),
        sell_order_count=1,
        exchange=position_bt.get("exchange", "NFO"),
        symbol=position_bt.get("symbol", ""),
    )
    net_pnl = gross_pnl - charges["total"]
    bt_capital += net_pnl
    exit_dt = exit_candle["dt"] if exit_candle is not None else position_bt.get("last_dt", position_bt.get("entry_dt"))
    realistic_register_exit_block(position_bt, reason, net_pnl, exit_dt, blocks)
    entry_exec = position_bt.get("entry_execution", {})
    trade = {
        "time": position_bt["entry_time"],
        "exit_time": exit_dt.strftime("%H:%M:%S"),
        "type": position_bt["trade_type"],
        "signal": position_bt["signal"],
        "symbol": position_bt["symbol"],
        "entry": round(float(position_bt["entry"]), 2),
        "exit": round(float(exit_price), 2),
        "raw_entry": round(float(position_bt.get("raw_entry", position_bt["entry"])), 2),
        "raw_exit": round(float(raw_exit if raw_exit is not None else exit_price), 2),
        "qty": int(position_bt["qty"]),
        "gross_pnl": round(float(gross_pnl), 2),
        "charges": charges["total"],
        "buy_charges": charges.get("buy_charges", charges.get("buy_total", 0)),
        "sell_charges": charges.get("sell_charges", charges.get("sell_total", 0)),
        "net_pnl": round(float(net_pnl), 2),
        "pnl": round(float(net_pnl), 2),
        "reason": reason,
        "entry_reason": position_bt.get("entry_reason", ""),
        "candle_confirmation": position_bt.get("candle_confirmation", ""),
        "trail_log": " || ".join(position_bt.get("trail_log", [])[-8:]),
        "entry_execution": entry_exec,
        "exit_execution": exit_exec or {},
        "entry_option_ohlc": position_bt.get("entry_option_ohlc", {}),
        "exit_option_ohlc": candle_to_ohlc_dict(exit_candle),
        "option_move": f"{position_bt.get('raw_entry', position_bt['entry']):.2f}->{position_bt.get('peak', position_bt['entry']):.2f}->{raw_exit if raw_exit is not None else exit_price:.2f}",
    }
    trades.append(trade)
    detail_logs.append(
        f"{trade['time']}->{trade['exit_time']} {trade['symbol']} {trade['signal']} "
        f"raw {trade['raw_entry']:.2f}->{trade['raw_exit']:.2f} fill {trade['entry']:.2f}->{trade['exit']:.2f} "
        f"net {trade['pnl']:.2f} | {reason}"
    )
    return bt_capital


def candle_to_ohlc_dict(row):
    if row is None:
        return {}
    return {
        "time": row["dt"].strftime("%H:%M:%S") if hasattr(row.get("dt"), "strftime") else str(row.get("time", "")),
        "open": round(float(row.get("open", 0) or 0), 2),
        "high": round(float(row.get("high", 0) or 0), 2),
        "low": round(float(row.get("low", 0) or 0), 2),
        "close": round(float(row.get("close", 0) or 0), 2),
        "volume": round(float(row.get("volume", 0) or 0), 2),
    }


def live_trades_for_backtest_day(day):
    day_text = day.strftime("%Y-%m-%d")
    return [trade for trade in trade_history if str(trade.get("date", "")) == day_text]


def parse_trade_clock(day, value):
    try:
        return dt.datetime.combine(day, dt.time.fromisoformat(str(value)[:8]))
    except Exception:
        return None


def build_accuracy_comparison(day, backtest_trades):
    live = live_trades_for_backtest_day(day)
    lines = ["", "ACCURACY VS LIVE PAPER"]
    if not live:
        lines.append("No live paper trades found for this date.")
        return lines
    lines.append(f"Live trades: {len(live)} | Backtest trades: {len(backtest_trades)}")
    count = max(len(live), len(backtest_trades))
    for index in range(min(count, 20)):
        bt_trade = backtest_trades[index] if index < len(backtest_trades) else None
        live_trade = live[index] if index < len(live) else None
        if not bt_trade or not live_trade:
            lines.append(f"#{index + 1}: mismatch count | live={bool(live_trade)} backtest={bool(bt_trade)}")
            continue
        bt_time = parse_trade_clock(day, bt_trade.get("time"))
        live_time = parse_trade_clock(day, live_trade.get("time"))
        timing = ""
        if bt_time and live_time:
            timing = f"{abs((bt_time - live_time).total_seconds()) / 60:.1f}m"
        entry_diff = bt_float(bt_trade.get("entry")) - bt_float(live_trade.get("entry"))
        exit_diff = bt_float(bt_trade.get("exit")) - bt_float(live_trade.get("exit"))
        lines.append(
            f"#{index + 1}: live {live_trade.get('signal')} {live_trade.get('symbol')} @ {live_trade.get('time')} "
            f"vs bt {bt_trade.get('signal')} {bt_trade.get('symbol')} @ {bt_trade.get('time')} | "
            f"time diff {timing or '--'} | entry diff {entry_diff:.2f} | exit diff {exit_diff:.2f}"
        )
    return lines


def build_realistic_backtest_report(mode, day, df, start_capital, final_capital, trades, stop_reason, skipped_entries, detail_logs):
    pnl_total = final_capital - start_capital
    gross_total = sum(bt_float(trade.get("gross_pnl")) for trade in trades)
    charges_total = sum(bt_float(trade.get("charges")) for trade in trades)
    wins = sum(1 for trade in trades if bt_float(trade.get("pnl")) > 0)
    losses = sum(1 for trade in trades if bt_float(trade.get("pnl")) <= 0)
    win_rate = (wins / len(trades) * 100) if trades else 0
    ret = (pnl_total / start_capital * 100) if start_capital else 0
    lines = [
        "REALISTIC MODE BACKTEST REPORT",
        f"Mode: {mode}",
        "Strategy Source: Live paper bot mirror",
        "Spot Source: Angel historic NIFTY candles",
        "Premium Source: REAL Angel NFO option candles only",
        "Execution: actual option OHLC + deterministic intrabar SL/target path",
        "Missing option candle rule: trade skipped",
        f"Slippage: {realistic_slippage_percent():.2f}% | Spread: {realistic_spread_percent():.2f}% | Liquidity impact: {realistic_liquidity_impact_percent():.2f}% per qty/volume",
        f"Date: {day.strftime('%Y-%m-%d')}",
        f"Start Capital: {start_capital:.2f}",
        f"Final Capital: {final_capital:.2f}",
        f"Gross P&L: {gross_total:.2f}",
        f"Charges: {charges_total:.2f}",
        f"Net P&L: {pnl_total:.2f}",
        f"Return: {ret:.2f}%",
        f"Spot Candles: {len(df)}",
        f"Trades: {len(trades)}",
        f"Wins: {wins}",
        f"Losses: {losses}",
        f"Win Rate: {win_rate:.2f}%",
        f"Skipped Entries: {len(skipped_entries)}",
    ]
    if stop_reason:
        lines.append(f"Stop Reason: {stop_reason}")
    lines.extend(build_accuracy_comparison(day, trades))
    lines.extend(["", "TRADES"])
    if trades:
        for trade in trades[-30:]:
            lines.append(
                f"{trade['time']} -> {trade['exit_time']} | {trade.get('type', '')} | {trade['signal']} | {trade['symbol']} | "
                f"Raw {trade.get('raw_entry', trade['entry']):.2f}->{trade.get('raw_exit', trade['exit']):.2f} | "
                f"Fill {trade['entry']:.2f}->{trade['exit']:.2f} | Qty {trade['qty']} | "
                f"Gross {trade.get('gross_pnl', trade['pnl']):.2f} | Charges {trade.get('charges', 0):.2f} | "
                f"Net {trade['pnl']:.2f} | {trade['reason']} | {trade.get('entry_reason', '')}"
            )
            if trade.get("trail_log"):
                lines.append(f"  Trail: {trade['trail_log']}")
    else:
        lines.append("No closed trade")
    if skipped_entries:
        lines.extend(["", "SKIPPED / MISSED SETUPS"])
        for item in skipped_entries[-40:]:
            lines.append(item)
    if detail_logs:
        lines.extend(["", "DETAIL LOGS"])
        for item in detail_logs[-60:]:
            lines.append(item)
    summary = f"REALISTIC {day.strftime('%Y-%m-%d')} | Trades {len(trades)} | P&L {pnl_total:.2f} | Return {ret:.2f}%"
    return summary, "\n".join(lines)


def run_realistic_backtest_day(mode, day, start_capital):
    bt_capital = start_capital
    df = fetch_backtest_candles(day)
    if len(df) < 30:
        raise RuntimeError(f"Not enough candles for {day.strftime('%Y-%m-%d')}")
    orb_block = df[(df["clock"] >= ORB_START) & (df["clock"] < ORB_END)]
    if orb_block.empty:
        orb_block = df.head(5)
    bt_orb_high = float(orb_block["high"].max())
    bt_orb_low = float(orb_block["low"].min())
    bt_gap_day = backtest_gap_day_mode(df, day)
    trade_end_time = EXPIRY_TRADE_END if is_expiry_day(day) else TRADE_END
    bt_entry_cutoff = backtest_entry_cutoff_time(trade_end_time)
    sl_percent, target_percent = backtest_sl_target_percents(day)
    position_bt = None
    trades = []
    stop_reason = ""
    profit_floor = None
    profit_lock_level = 0.0
    skipped_entries = []
    detail_logs = []
    blocks = {"direction": {}, "symbol": {}, "strike": {}, "post_exit_until": None}

    for index in range(21, len(df)):
        row = df.iloc[index]
        now_clock = row["clock"]
        now_dt = row["dt"]
        if now_clock < TRADE_START:
            continue
        if now_clock > trade_end_time:
            break

        if position_bt is not None:
            option_row, option_index = option_candle_for_time(position_bt["option_df"], now_dt)
            if option_row is None:
                detail_logs.append(f"{now_dt.strftime('%H:%M:%S')} option candle missing while position open: {position_bt['symbol']}")
            else:
                position_bt["current_index"] = index
                position_bt["last_dt"] = option_row["dt"]
                position_bt["last_option_candle"] = option_row
                position_bt["peak"] = max(float(position_bt.get("peak", position_bt["entry"])), float(option_row["high"]))
                exit_price, reason, exit_exec, raw_exit = realistic_intrabar_exit(position_bt, option_row, detail_logs)
                if exit_price is not None:
                    bt_capital = close_realistic_backtest_trade(
                        position_bt, exit_price, reason, bt_capital, trades, option_row, exit_exec, raw_exit, blocks, detail_logs
                    )
                    position_bt = None

        live_equity = bt_capital
        if position_bt is not None:
            raw_close = float(position_bt.get("ltp", position_bt["entry"]))
            sell_fill, _ = realistic_sell_fill(raw_close, None, position_bt["qty"], position_bt.get("lot_size", FAST_LOT_SIZE))
            open_charges = calculate_option_charges(
                position_bt["entry"], sell_fill, position_bt["qty"],
                entry_qty=position_bt.get("entry_qty", position_bt["qty"]),
                buy_order_count=position_bt.get("entry_order_count", 1),
                sell_order_count=1,
                exchange=position_bt.get("exchange", "NFO"),
                symbol=position_bt.get("symbol", ""),
            )
            live_equity += ((sell_fill - position_bt["entry"]) * position_bt["qty"]) - open_charges["total"]
        if live_equity <= start_capital * (1 - MAX_DAILY_LOSS):
            if position_bt is not None:
                option_row = position_bt.get("last_option_candle")
                if option_row is None:
                    option_row = position_bt.get("entry_candle")
                sell_fill, exec_info = realistic_sell_fill(float(position_bt.get("ltp", position_bt["entry"])), option_row, position_bt["qty"], position_bt.get("lot_size", FAST_LOT_SIZE))
                bt_capital = close_realistic_backtest_trade(position_bt, sell_fill, "BT DAILY LOSS", bt_capital, trades, option_row, exec_info, position_bt.get("ltp"), blocks, detail_logs)
                position_bt = None
            stop_reason = f"Stopped: daily loss limit hit ({MAX_DAILY_LOSS * 100:.1f}%)"
            break
        profit_lock_level, profit_floor, lock_changed = backtest_profit_lock_update(start_capital, live_equity, profit_lock_level, profit_floor)
        if not lock_changed and profit_floor is not None and live_equity < profit_floor:
            if position_bt is not None:
                option_row = position_bt.get("last_option_candle")
                if option_row is None:
                    option_row = position_bt.get("entry_candle")
                sell_fill, exec_info = realistic_sell_fill(float(position_bt.get("ltp", position_bt["entry"])), option_row, position_bt["qty"], position_bt.get("lot_size", FAST_LOT_SIZE))
                bt_capital = close_realistic_backtest_trade(position_bt, sell_fill, "BT PROFIT FLOOR", bt_capital, trades, option_row, exec_info, position_bt.get("ltp"), blocks, detail_logs)
                position_bt = None
            stop_reason = "Stopped: profit floor protected"
            break

        if position_bt is None:
            if now_clock >= bt_entry_cutoff:
                continue
            signal, trade_type, score = backtest_signal(df, index, bt_orb_high, bt_orb_low, bt_gap_day)
            if not signal:
                if score >= 3:
                    skipped_entries.append(f"{now_dt.strftime('%H:%M:%S')} WAIT score {score}/5 | candle confirmation incomplete")
                continue
            option, notes = choose_realistic_backtest_option(signal, row["close"], bt_capital, day, now_dt, trade_type, blocks)
            if option is None:
                skipped_entries.append(f"{now_dt.strftime('%H:%M:%S')} {signal} {trade_type} score {score}/5 skipped | " + " ; ".join(notes[-4:]))
                continue
            lot_size = int(option.get("lot_size") or FAST_LOT_SIZE)
            qty, max_lots = backtest_qty(bt_capital, option["premium"], trade_type, lot_size)
            qty = backtest_risk_cap_qty(bt_capital, qty, option["premium"], lot_size, sl_percent)
            if qty <= 0:
                skipped_entries.append(f"{now_dt.strftime('%H:%M:%S')} {option['symbol']} qty blocked by risk/capital")
                continue
            entry_price, entry_exec = realistic_execution_price(option["raw_premium"], option["entry_candle"], "BUY", qty, lot_size)
            position_bt = {
                "signal": signal,
                "trade_type": trade_type,
                "symbol": option["symbol"],
                "option": option,
                "option_df": option["option_df"],
                "exchange": option["exchange"],
                "lot_size": lot_size,
                "entry": entry_price,
                "raw_entry": option["raw_premium"],
                "entry_spot": float(row["close"]),
                "entry_time": now_dt.strftime("%H:%M:%S"),
                "entry_dt": now_dt,
                "entry_index": index,
                "entry_option_index": option["entry_option_index"],
                "entry_candle": option["entry_candle"],
                "entry_option_ohlc": candle_to_ohlc_dict(option["entry_candle"]),
                "entry_execution": entry_exec,
                "ltp": option["raw_premium"],
                "qty": qty,
                "entry_qty": qty,
                "entry_order_count": 1,
                "planned_full_qty": max_lots * lot_size,
                "sl": entry_price * (1 - sl_percent / 100),
                "target": entry_price * (1 + target_percent / 100),
                "peak": option["raw_premium"],
                "initial_risk": entry_price * (sl_percent / 100),
                "score": score,
                "entry_reason": f"{signal} {trade_type} score {score}/5 | live mirror filters passed",
                "candle_confirmation": f"spot {now_dt.strftime('%H:%M:%S')} close {float(row['close']):.2f}; option raw close {option['raw_premium']:.2f}",
                "trail_log": [],
            }
            detail_logs.append(
                f"{now_dt.strftime('%H:%M:%S')} ENTRY {option['symbol']} {signal} {trade_type} | "
                f"spot {float(row['close']):.2f} | option raw {option['raw_premium']:.2f} fill {entry_price:.2f} | qty {qty}"
            )

    if position_bt is not None:
        option_row = position_bt.get("last_option_candle")
        if option_row is None:
            option_row = position_bt["option_df"].iloc[-1]
        sell_fill, exec_info = realistic_sell_fill(float(option_row["close"]), option_row, position_bt["qty"], position_bt.get("lot_size", FAST_LOT_SIZE))
        bt_capital = close_realistic_backtest_trade(position_bt, sell_fill, "BT EOD EXIT", bt_capital, trades, option_row, exec_info, float(option_row["close"]), blocks, detail_logs)

    summary, report = build_realistic_backtest_report(mode, day, df, start_capital, bt_capital, trades, stop_reason, skipped_entries, detail_logs)
    return {
        "day": day,
        "summary": summary,
        "report": report,
        "start_capital": start_capital,
        "final_capital": bt_capital,
        "trades": trades,
        "stop_reason": stop_reason,
        "candles": len(df),
        "skipped": skipped_entries,
    }


def run_realistic_monthly_backtest(payload, mode, start_capital):
    start_day, end_day = parse_backtest_month(payload.get("month") or payload.get("date"))
    running_capital = start_capital
    day_results = []
    skipped = []
    for day in backtest_market_days(start_day, end_day):
        try:
            result = run_realistic_backtest_day("REALISTIC", day, running_capital)
            running_capital = float(result["final_capital"])
            day_results.append(result)
        except Exception as exc:
            skipped.append((day, str(exc)[:180]))
    if not day_results and skipped:
        raise RuntimeError("Realistic monthly backtest skipped all days: " + skipped[-1][1])
    return build_monthly_backtest_report(mode, start_day, end_day, start_capital, running_capital, day_results, skipped)


_OKAI_ESTIMATED_RUN_MOBILE_BACKTEST = run_mobile_backtest


def run_mobile_backtest(payload=None):
    payload = payload or {}
    mode = str(payload.get("mode", "FAST") or "FAST").upper()
    start_capital = float(payload.get("capital") or paper_capital or capital)
    if realistic_monthly_backtest_mode(mode):
        return run_realistic_monthly_backtest(payload, "REALISTIC_MONTHLY", start_capital)
    if realistic_backtest_mode(mode):
        day = parse_backtest_day(payload.get("date"))
        result = run_realistic_backtest_day("REALISTIC", day, start_capital)
        return result["summary"], result["report"]
    return _OKAI_ESTIMATED_RUN_MOBILE_BACKTEST(payload)

# ===== END PATCH =====


# ===== OPTION KING AI PATCH: PERSIST CAPITAL ACROSS SERVER UPDATES =====
# Version: 2026.05.16-capital-state-1

CAPITAL_STATE_PATH = os.path.join(DATA_DIR, "capital_state.json")


def save_capital_state(reason=""):
    """Persist live paper capital so restart/update cannot reset it."""
    try:
        ensure_dirs()
        payload = {
            "capital": float(capital),
            "paper_capital": float(paper_capital),
            "daily_pnl": float(daily_pnl),
            "trades_taken": int(trades_taken),
            "market_day": market_day_text(),
            "updated_at": market_now().isoformat(timespec="seconds"),
            "reason": reason,
        }
        tmp_path = CAPITAL_STATE_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2)
        os.replace(tmp_path, CAPITAL_STATE_PATH)
        return payload
    except Exception as exc:
        gui_log(f"Capital state save skipped: {exc}")
        return None


def load_capital_state():
    try:
        if not os.path.exists(CAPITAL_STATE_PATH):
            return None
        with open(CAPITAL_STATE_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            return None
        return data
    except Exception as exc:
        gui_log(f"Capital state load skipped: {exc}")
        return None


_OKAI_CAPITAL_BASE_LOAD_TRADE_HISTORY = load_trade_history_from_disk


def load_trade_history_from_disk():
    """Load reports, then restore saved capital as the source of truth."""
    global capital, paper_capital, daily_pnl, trades_taken

    _OKAI_CAPITAL_BASE_LOAD_TRADE_HISTORY()

    state = load_capital_state()
    today_text = market_day_text()

    if state:
        saved_capital = float(state.get("capital", capital) or capital)
        saved_paper_capital = float(state.get("paper_capital", saved_capital) or saved_capital)
        saved_daily_pnl = float(state.get("daily_pnl", 0) or 0)
        saved_trades_taken = int(float(state.get("trades_taken", trades_taken) or 0))
        saved_day = str(state.get("market_day", "") or "")

        if saved_day == today_text:
            capital = saved_capital
            paper_capital = saved_paper_capital
            daily_pnl = saved_daily_pnl
            trades_taken = saved_trades_taken
            gui_log(
                f"Capital restored from saved state: {capital:.2f} | "
                f"Daily P&L: {daily_pnl:.2f} | Trades: {trades_taken}"
            )
        else:
            capital = saved_capital
            paper_capital = saved_capital
            daily_pnl = 0.0
            trades_taken = 0
            save_capital_state("new_market_day_carry_forward")
            gui_log(f"New market day capital carry-forward: {capital:.2f}")
    else:
        save_capital_state("initial_state_created")
        gui_log(f"Capital state created: {capital:.2f}")


_OKAI_CAPITAL_BASE_UPDATE_CAPITAL = update_capital


def update_capital(new_capital):
    _OKAI_CAPITAL_BASE_UPDATE_CAPITAL(new_capital)
    save_capital_state("manual_capital_update")


_OKAI_CAPITAL_BASE_CLOSE_POSITION = close_position


def close_position(exit_price, reason):
    result = _OKAI_CAPITAL_BASE_CLOSE_POSITION(exit_price, reason)
    if result is not None:
        save_capital_state(f"position_closed:{reason}")
    return result


_OKAI_CAPITAL_BASE_CHECK_PARTIAL_EXIT = check_partial_exit


def check_partial_exit():
    before_qty = int(position.get("qty", 0) or 0) if position else 0
    before_capital = float(capital)
    _OKAI_CAPITAL_BASE_CHECK_PARTIAL_EXIT()
    after_qty = int(position.get("qty", 0) or 0) if position else 0
    if before_qty != after_qty or float(capital) != before_capital:
        save_capital_state("partial_exit")

# ===== END PATCH =====

if __name__ == "__main__":
    main()
