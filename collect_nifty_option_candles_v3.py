"""Day-range NIFTY option candle collector.

This wrapper reuses the safe V2 Angel login/storage helpers, but selects option
strikes from the complete intraday NIFTY low-to-high range instead of using
only the closing ATM. That prevents morning/afternoon ATM contracts from being
missed on volatile days. It does not import app.py and never sends orders.
"""

from __future__ import annotations

import argparse
import math
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Tuple

import collect_nifty_option_candles_v2 as v2


def spot_range(rows: List[List[Any]]) -> Tuple[float, float, float]:
    lows: List[float] = []
    highs: List[float] = []

    for row in rows:
        if not isinstance(row, list) or len(row) < 5:
            continue
        try:
            high = float(row[2])
            low = float(row[3])
        except Exception:
            continue
        if math.isfinite(high) and high > 0:
            highs.append(high)
        if math.isfinite(low) and low > 0:
            lows.append(low)

    close = v2.last_close(rows)
    if not lows or not highs or close is None:
        raise RuntimeError("Unable to calculate valid spot day range")

    return min(lows), max(highs), close


def nearest_strike(strikes: List[int], price: float) -> int:
    return min(strikes, key=lambda strike: (abs(strike - price), strike))


def select_chain_day_range(
    contracts: List[Dict[str, Any]],
    trade_date: date,
    spot_low: float,
    spot_high: float,
    spot_close: float,
    wings: int,
) -> Tuple[date, int, int, int, List[Dict[str, Any]]]:
    expiry = v2.nearest_expiry(contracts, trade_date)
    expiry_contracts = [item for item in contracts if item["expiry"] == expiry]
    strikes = sorted({int(item["strike"]) for item in expiry_contracts})
    if not strikes:
        raise RuntimeError(f"No strikes found for expiry {expiry}")

    low_atm = nearest_strike(strikes, spot_low)
    high_atm = nearest_strike(strikes, spot_high)
    close_atm = nearest_strike(strikes, spot_close)

    low_index = max(0, min(strikes.index(low_atm), strikes.index(high_atm)) - wings)
    high_index = min(
        len(strikes),
        max(strikes.index(low_atm), strikes.index(high_atm)) + wings + 1,
    )
    selected_strikes = set(strikes[low_index:high_index])

    selected = [
        item
        for item in expiry_contracts
        if int(item["strike"]) in selected_strikes
    ]
    selected.sort(key=lambda item: (int(item["strike"]), item["option_type"]))
    return expiry, low_atm, high_atm, close_atm, selected


def process_day(
    api: Any,
    contracts: List[Dict[str, Any]],
    trade_date: date,
    wings: int,
    dry_run: bool,
    force: bool,
    manifest: Dict[Tuple[str, str], Dict[str, str]],
) -> Dict[str, int]:
    summary = {"saved": 0, "skipped": 0, "failed": 0, "contracts": 0}

    spot_rows = v2.get_candles(api, v2.SPOT_EXCHANGE, v2.SPOT_TOKEN, trade_date)
    if not spot_rows:
        print(trade_date.isoformat(), "| NO_SPOT_DATA")
        return summary

    spot_low, spot_high, spot_close = spot_range(spot_rows)
    expiry, low_atm, high_atm, close_atm, selected = select_chain_day_range(
        contracts,
        trade_date,
        spot_low,
        spot_high,
        spot_close,
        wings,
    )
    summary["contracts"] = len(selected)

    print(
        trade_date.isoformat(),
        "| spot_low =", round(spot_low, 2),
        "| spot_high =", round(spot_high, 2),
        "| spot_close =", round(spot_close, 2),
        "| expiry =", expiry.isoformat(),
        "| dynamic_atm =", f"{low_atm}-{high_atm}",
        "| close_atm =", close_atm,
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

    day_dir = v2.OUTPUT_ROOT / trade_date.strftime("%Y%m%d")
    spot_path = day_dir / (
        f"SPOT_NIFTY_{v2.SPOT_TOKEN}_{v2.INTERVAL}_{trade_date:%Y%m%d}.json"
    )
    v2.write_json(
        spot_path,
        {
            "schema_version": 3,
            "instrument": "NIFTY",
            "exchange": v2.SPOT_EXCHANGE,
            "token": v2.SPOT_TOKEN,
            "interval": v2.INTERVAL,
            "trade_date": trade_date.isoformat(),
            "spot_low": spot_low,
            "spot_high": spot_high,
            "spot_close": spot_close,
            "selection_method": "full_day_spot_range",
            "data": spot_rows,
        },
    )

    for item in selected:
        file_name = (
            f"NFO_{item['token']}_{v2.safe_symbol(item['symbol'])}_"
            f"{v2.INTERVAL}_{trade_date:%Y%m%d}.json"
        )
        output_path = day_dir / file_name
        key = (trade_date.isoformat(), str(item["token"]))

        if output_path.exists() and not force:
            summary["skipped"] += 1
            continue

        rows = v2.get_candles(api, "NFO", str(item["token"]), trade_date)
        time.sleep(0.55)
        if not rows:
            summary["failed"] += 1
            continue

        payload = {
            "schema_version": 3,
            "instrument": "NIFTY",
            "exchange": "NFO",
            "token": str(item["token"]),
            "symbol": item["symbol"],
            "expiry": item["expiry"].isoformat(),
            "strike": int(item["strike"]),
            "option_type": item["option_type"],
            "interval": v2.INTERVAL,
            "trade_date": trade_date.isoformat(),
            "spot_low": spot_low,
            "spot_high": spot_high,
            "spot_close": spot_close,
            "low_atm_strike": low_atm,
            "high_atm_strike": high_atm,
            "atm_strike": close_atm,
            "selection_method": "full_day_spot_range",
            "data": rows,
        }
        v2.write_json(output_path, payload)
        manifest[key] = {
            "trade_date": trade_date.isoformat(),
            "exchange": "NFO",
            "token": str(item["token"]),
            "symbol": item["symbol"],
            "expiry": item["expiry"].isoformat(),
            "strike": str(item["strike"]),
            "option_type": item["option_type"],
            "spot_close": f"{spot_close:.2f}",
            "atm_strike": str(close_atm),
            "rows": str(len(rows)),
            "file": str(output_path),
        }
        summary["saved"] += 1

    v2.save_manifest(manifest)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Single date YYYY-MM-DD")
    parser.add_argument("--date-from", help="Start date YYYY-MM-DD")
    parser.add_argument("--date-to", help="End date YYYY-MM-DD")
    parser.add_argument("--wings", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.wings < 0 or args.wings > 10:
        raise SystemExit("--wings must be between 0 and 10")

    if args.date:
        start = end = v2.parse_trade_date(args.date)
    elif args.date_from and args.date_to:
        start = v2.parse_trade_date(args.date_from)
        end = v2.parse_trade_date(args.date_to)
    else:
        raise SystemExit("Use --date or both --date-from and --date-to")

    if end < start:
        raise SystemExit("date-to cannot be earlier than date-from")

    master, master_path = v2.load_master()
    contracts = v2.build_contracts(master)
    api, config_path = v2.login()
    manifest = v2.load_manifest()

    print("=== NIFTY OPTION COLLECTOR V3 ===")
    print("config =", config_path)
    print("instrument_master =", master_path)
    print("master_contracts =", len(contracts))
    print("selection = FULL_DAY_SPOT_RANGE")
    print("dry_run =", args.dry_run)
    print("orders = DISABLED")
    print()

    totals = {"saved": 0, "skipped": 0, "failed": 0, "contracts": 0, "days": 0}
    for trade_date in v2.trading_dates(start, end):
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
    print("manifest =", v2.MANIFEST_PATH)
    print("server/orders = UNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
