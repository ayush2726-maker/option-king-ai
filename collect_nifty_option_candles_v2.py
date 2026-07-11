"""Standalone NIFTY option candle collector with permanent contract metadata.

Safety:
- does not import or modify app.py
- does not place, modify, or cancel orders
- reads local Angel credentials and instrument master only
- stores each option file with token + symbol + expiry + strike metadata

Typical first check:
    python collect_nifty_option_candles_v2.py --date 2026-07-10 --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pyotp
from SmartApi import SmartConnect


SPOT_TOKEN = "99926000"
SPOT_EXCHANGE = "NSE"
INTERVAL = "ONE_MINUTE"
MARKET_FROM = "09:15"
MARKET_TO = "15:30"
OUTPUT_ROOT = Path("data/angel_cache/option_candles_v2")
MANIFEST_PATH = OUTPUT_ROOT / "manifest.csv"

CONFIG_CANDIDATES = [
    Path("users/owner/config.json"),
    Path("config.json"),
]
MASTER_CANDIDATES = [
    Path("data/angel_cache/OpenAPIScripMaster.json"),
    Path("users/owner/data/angel_cache/OpenAPIScripMaster.json"),
    Path("OpenAPIScripMaster.json"),
]

SYMBOL_EXPIRY_RE = re.compile(r"^NIFTY(\d{2}[A-Z]{3}\d{2})(\d+)(CE|PE)$", re.I)


def recursive_find(obj: Any, aliases: Sequence[str]) -> Optional[Any]:
    wanted = {value.lower() for value in aliases}
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).lower() in wanted and value not in (None, ""):
                return value
        for value in obj.values():
            found = recursive_find(value, aliases)
            if found not in (None, ""):
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = recursive_find(value, aliases)
            if found not in (None, ""):
                return found
    return None


def load_credentials() -> Tuple[Dict[str, str], Path]:
    aliases = {
        "api_key": ("api_key", "angel_api_key", "smartapi_api_key"),
        "client_id": ("client_id", "angel_client_id", "user_id"),
        "password": ("password", "angel_password", "pin", "mpin"),
        "totp_secret": ("totp_secret", "angel_totp_secret", "totp_key"),
    }

    for path in CONFIG_CANDIDATES:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        result: Dict[str, str] = {}
        for name, keys in aliases.items():
            value = recursive_find(payload, keys)
            if value not in (None, ""):
                result[name] = str(value).strip()

        if all(result.get(key) for key in aliases):
            return result, path

    raise RuntimeError(
        "Angel credentials not found in users/owner/config.json or config.json"
    )


def load_master() -> Tuple[List[Dict[str, Any]], Path]:
    for path in MASTER_CANDIDATES:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        if isinstance(payload, list) and payload:
            return [item for item in payload if isinstance(item, dict)], path
    raise RuntimeError("OpenAPIScripMaster.json not found or invalid")


def parse_expiry(item: Dict[str, Any]) -> Optional[date]:
    raw = str(item.get("expiry") or "").strip().upper()
    for fmt in ("%d%b%Y", "%d%b%y", "%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except Exception:
            pass

    symbol = str(item.get("symbol") or item.get("tradingsymbol") or "").upper()
    match = SYMBOL_EXPIRY_RE.match(symbol)
    if match:
        try:
            return datetime.strptime(match.group(1), "%d%b%y").date()
        except Exception:
            pass
    return None


def normalize_strike(value: Any) -> Optional[int]:
    try:
        number = float(value)
    except Exception:
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    if number > 100000:
        number /= 100.0
    return int(round(number))


def build_contracts(master: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    contracts: List[Dict[str, Any]] = []
    for item in master:
        exchange = str(item.get("exch_seg") or "").upper()
        name = str(item.get("name") or "").upper()
        instrument = str(item.get("instrumenttype") or "").upper()
        symbol = str(item.get("symbol") or item.get("tradingsymbol") or "").upper()
        token = str(item.get("token") or "").strip()

        if exchange != "NFO" or name != "NIFTY" or instrument != "OPTIDX":
            continue
        if not token or not symbol.endswith(("CE", "PE")):
            continue

        expiry = parse_expiry(item)
        strike = normalize_strike(item.get("strike"))
        if not expiry or not strike:
            continue

        contracts.append(
            {
                "exchange": "NFO",
                "token": token,
                "symbol": symbol,
                "expiry": expiry,
                "strike": strike,
                "option_type": symbol[-2:],
            }
        )
    if not contracts:
        raise RuntimeError("No NIFTY OPTIDX contracts found in instrument master")
    return contracts


def parse_trade_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def trading_dates(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


def api_rows(response: Any) -> List[List[Any]]:
    if not isinstance(response, dict):
        return []
    data = response.get("data")
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, list) and len(row) >= 5]


def get_candles(
    api: SmartConnect,
    exchange: str,
    token: str,
    trade_date: date,
    retries: int = 4,
) -> List[List[Any]]:
    params = {
        "exchange": exchange,
        "symboltoken": str(token),
        "interval": INTERVAL,
        "fromdate": f"{trade_date.isoformat()} {MARKET_FROM}",
        "todate": f"{trade_date.isoformat()} {MARKET_TO}",
    }

    last_error = "unknown error"
    for attempt in range(1, retries + 1):
        try:
            response = api.getCandleData(params)
            rows = api_rows(response)
            if rows:
                return rows
            if isinstance(response, dict):
                last_error = str(response.get("message") or response)
            else:
                last_error = str(response)
        except Exception as exc:
            last_error = repr(exc)

        if attempt < retries:
            time.sleep(1.5 * attempt)

    print(
        "CANDLE_FETCH_FAILED",
        exchange,
        token,
        trade_date.isoformat(),
        "|",
        last_error[:180],
    )
    return []


def last_close(rows: List[List[Any]]) -> Optional[float]:
    for row in reversed(rows):
        try:
            value = float(row[4])
        except Exception:
            continue
        if math.isfinite(value) and value > 0:
            return value
    return None


def nearest_expiry(contracts: List[Dict[str, Any]], trade_date: date) -> date:
    expiries = sorted({item["expiry"] for item in contracts if item["expiry"] >= trade_date})
    if not expiries:
        raise RuntimeError(f"No unexpired NIFTY option contract for {trade_date}")
    return expiries[0]


def select_chain(
    contracts: List[Dict[str, Any]],
    trade_date: date,
    spot_close: float,
    wings: int,
) -> Tuple[date, int, List[Dict[str, Any]]]:
    expiry = nearest_expiry(contracts, trade_date)
    expiry_contracts = [item for item in contracts if item["expiry"] == expiry]
    strikes = sorted({item["strike"] for item in expiry_contracts})
    if not strikes:
        raise RuntimeError(f"No strikes found for expiry {expiry}")

    atm = min(strikes, key=lambda strike: (abs(strike - spot_close), strike))
    atm_index = strikes.index(atm)
    low = max(0, atm_index - wings)
    high = min(len(strikes), atm_index + wings + 1)
    selected_strikes = set(strikes[low:high])

    selected = [
        item
        for item in expiry_contracts
        if item["strike"] in selected_strikes
    ]
    selected.sort(key=lambda item: (item["strike"], item["option_type"]))
    return expiry, atm, selected


def safe_symbol(symbol: str) -> str:
    return re.sub(r"[^A-Z0-9._-]+", "_", symbol.upper())


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def load_manifest() -> Dict[Tuple[str, str], Dict[str, str]]:
    rows: Dict[Tuple[str, str], Dict[str, str]] = {}
    if not MANIFEST_PATH.exists():
        return rows
    try:
        with MANIFEST_PATH.open("r", newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (str(row.get("trade_date") or ""), str(row.get("token") or ""))
                if all(key):
                    rows[key] = row
    except Exception:
        return {}
    return rows


def save_manifest(rows: Dict[Tuple[str, str], Dict[str, str]]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "trade_date",
        "exchange",
        "token",
        "symbol",
        "expiry",
        "strike",
        "option_type",
        "spot_close",
        "atm_strike",
        "rows",
        "file",
    ]
    temporary = MANIFEST_PATH.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for key in sorted(rows):
            writer.writerow({column: rows[key].get(column, "") for column in columns})
    temporary.replace(MANIFEST_PATH)


def login() -> Tuple[SmartConnect, Path]:
    credentials, config_path = load_credentials()
    api = SmartConnect(api_key=credentials["api_key"])
    otp = pyotp.TOTP(credentials["totp_secret"]).now()
    response = api.generateSession(
        credentials["client_id"],
        credentials["password"],
        otp,
    )
    if not isinstance(response, dict) or not response.get("status"):
        message = response.get("message") if isinstance(response, dict) else response
        raise RuntimeError(f"Angel login failed: {message}")
    return api, config_path


def process_day(
    api: SmartConnect,
    contracts: List[Dict[str, Any]],
    trade_date: date,
    wings: int,
    dry_run: bool,
    force: bool,
    manifest: Dict[Tuple[str, str], Dict[str, str]],
) -> Dict[str, int]:
    summary = {"saved": 0, "skipped": 0, "failed": 0, "contracts": 0}

    spot_rows = get_candles(api, SPOT_EXCHANGE, SPOT_TOKEN, trade_date)
    if not spot_rows:
        print(trade_date.isoformat(), "| NO_SPOT_DATA")
        return summary

    spot_close = last_close(spot_rows)
    if spot_close is None:
        print(trade_date.isoformat(), "| INVALID_SPOT_CLOSE")
        return summary

    expiry, atm, selected = select_chain(
        contracts,
        trade_date,
        spot_close,
        wings,
    )
    summary["contracts"] = len(selected)

    print(
        trade_date.isoformat(),
        "| spot_close =", round(spot_close, 2),
        "| expiry =", expiry.isoformat(),
        "| atm =", atm,
        "| contracts =", len(selected),
    )

    for item in selected:
        print(
            " ",
            item["token"],
            "|",
            item["symbol"],
            "| strike =", item["strike"],
            "|", item["option_type"],
        )

    if dry_run:
        print(trade_date.isoformat(), "| DRY_RUN: no option files written")
        return summary

    day_dir = OUTPUT_ROOT / trade_date.strftime("%Y%m%d")
    spot_path = day_dir / f"SPOT_NIFTY_{SPOT_TOKEN}_{INTERVAL}_{trade_date:%Y%m%d}.json"
    write_json(
        spot_path,
        {
            "schema_version": 2,
            "instrument": "NIFTY",
            "exchange": SPOT_EXCHANGE,
            "token": SPOT_TOKEN,
            "interval": INTERVAL,
            "trade_date": trade_date.isoformat(),
            "spot_close": spot_close,
            "data": spot_rows,
        },
    )

    for item in selected:
        file_name = (
            f"NFO_{item['token']}_{safe_symbol(item['symbol'])}_"
            f"{INTERVAL}_{trade_date:%Y%m%d}.json"
        )
        output_path = day_dir / file_name
        key = (trade_date.isoformat(), item["token"])

        if output_path.exists() and not force:
            summary["skipped"] += 1
            continue

        rows = get_candles(api, "NFO", item["token"], trade_date)
        time.sleep(0.55)
        if not rows:
            summary["failed"] += 1
            continue

        payload = {
            "schema_version": 2,
            "instrument": "NIFTY",
            "exchange": "NFO",
            "token": item["token"],
            "symbol": item["symbol"],
            "expiry": item["expiry"].isoformat(),
            "strike": item["strike"],
            "option_type": item["option_type"],
            "interval": INTERVAL,
            "trade_date": trade_date.isoformat(),
            "spot_close": spot_close,
            "atm_strike": atm,
            "data": rows,
        }
        write_json(output_path, payload)
        manifest[key] = {
            "trade_date": trade_date.isoformat(),
            "exchange": "NFO",
            "token": item["token"],
            "symbol": item["symbol"],
            "expiry": item["expiry"].isoformat(),
            "strike": str(item["strike"]),
            "option_type": item["option_type"],
            "spot_close": f"{spot_close:.2f}",
            "atm_strike": str(atm),
            "rows": str(len(rows)),
            "file": str(output_path),
        }
        summary["saved"] += 1

    save_manifest(manifest)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Single date YYYY-MM-DD")
    parser.add_argument("--date-from", help="Start date YYYY-MM-DD")
    parser.add_argument("--date-to", help="End date YYYY-MM-DD")
    parser.add_argument("--wings", type=int, default=3, help="Strikes on each ATM side")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.wings < 0 or args.wings > 10:
        raise SystemExit("--wings must be between 0 and 10")

    if args.date:
        start = end = parse_trade_date(args.date)
    elif args.date_from and args.date_to:
        start = parse_trade_date(args.date_from)
        end = parse_trade_date(args.date_to)
    else:
        raise SystemExit("Use --date or both --date-from and --date-to")

    if end < start:
        raise SystemExit("date-to cannot be earlier than date-from")

    master, master_path = load_master()
    contracts = build_contracts(master)
    api, config_path = login()
    manifest = load_manifest()

    print("=== NIFTY OPTION COLLECTOR V2 ===")
    print("config =", config_path)
    print("instrument_master =", master_path)
    print("master_contracts =", len(contracts))
    print("dry_run =", args.dry_run)
    print("orders = DISABLED")
    print()

    totals = {"saved": 0, "skipped": 0, "failed": 0, "contracts": 0, "days": 0}
    for trade_date in trading_dates(start, end):
        totals["days"] += 1
        try:
            result = process_day(
                api,
                contracts,
                trade_date,
                args.wings,
                args.dry_run,
                args.force,
                manifest,
            )
        except Exception as exc:
            print(trade_date.isoformat(), "| DAY_FAILED |", repr(exc))
            totals["failed"] += 1
            continue
        for key in ("saved", "skipped", "failed", "contracts"):
            totals[key] += result[key]

    print()
    print("=== COLLECTOR SUMMARY ===")
    print("days_checked =", totals["days"])
    print("contracts_selected =", totals["contracts"])
    print("files_saved =", totals["saved"])
    print("files_skipped =", totals["skipped"])
    print("fetch_failures =", totals["failed"])
    print("manifest =", MANIFEST_PATH)
    print("server/orders = UNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
