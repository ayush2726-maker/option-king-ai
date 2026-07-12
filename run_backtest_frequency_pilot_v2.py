"""Run a strategy-consistent frequency pilot before a two-year backtest.

This script never seeds older CSV results. Every row is generated with the
current app.py and carries the current app.py SHA256 fingerprint. It is for
backtest diagnostics only and cannot place/modify/cancel live orders.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

FIELDS = [
    "date",
    "status",
    "summary",
    "stats",
    "report",
    "error",
    "app_sha256",
]
SUMMARY_RE = re.compile(
    r"Trades\s+(\d+)\s*\|\s*P&L\s+([-+]?\d+(?:\.\d+)?)",
    re.I,
)


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def app_hash() -> str:
    return hashlib.sha256(Path("app.py").read_bytes()).hexdigest()


def iter_weekdays(start: date, end: date):
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current.isoformat()
        current += timedelta(days=1)


def load_app():
    with open("/dev/null", "w") as devnull:
        with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
            import app
    return app


def normalize(trade_date: str, result: Any, fingerprint: str) -> Dict[str, str]:
    if isinstance(result, dict):
        summary = result.get("summary")
        stats = result.get("stats")
        report = result.get("report")
    elif isinstance(result, tuple):
        summary = result[0] if len(result) > 0 else ""
        report = result[1] if len(result) > 1 else ""
        stats = result[2] if len(result) > 2 else ""
    else:
        summary = result
        stats = ""
        report = ""

    useful_lines = [
        line.strip()
        for line in str(report or "").splitlines()
        if any(
            word in line.upper()
            for word in (
                "PREMIUM SOURCE",
                "CANDLES:",
                "GROSS P&L",
                "NET P&L",
                "TRADES:",
                "WINS:",
                "LOSSES:",
                "STOP REASON",
                "->",
                "AI TRADE QUALITY",
                "NO CLOSED TRADE",
            )
        )
    ]

    return {
        "date": trade_date,
        "status": "OK",
        "summary": str(summary or ""),
        "stats": json.dumps(stats, ensure_ascii=False, default=str),
        "report": "\n".join(useful_lines[-60:]),
        "error": "",
        "app_sha256": fingerprint,
    }


def run_one(app_module, trade_date: str, fingerprint: str) -> Dict[str, str]:
    try:
        with open("/dev/null", "w") as devnull:
            with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                result = app_module.run_mobile_backtest(
                    {"mode": "REALISTIC", "date": trade_date}
                )
        return normalize(trade_date, result, fingerprint)
    except Exception as exc:
        return {
            "date": trade_date,
            "status": "ERROR",
            "summary": "",
            "stats": "",
            "report": "",
            "error": f"{type(exc).__name__}: {str(exc)[:700]}",
            "app_sha256": fingerprint,
        }


def checkpoint(path: Path, rows: List[Dict[str, str]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-07-01")
    parser.add_argument("--end", default="2025-09-30")
    parser.add_argument("--delay", type=float, default=0.8)
    parser.add_argument(
        "--output",
        default="backtest_frequency_pilot_current_strategy.csv",
    )
    args = parser.parse_args()

    start = parse_date(args.start)
    end = parse_date(args.end)
    if end < start:
        raise SystemExit("end date must be on or after start date")

    output = Path(args.output)
    fingerprint = app_hash()
    app_module = load_app()
    dates = list(iter_weekdays(start, end))
    rows: List[Dict[str, str]] = []

    print("=== CURRENT STRATEGY FREQUENCY PILOT ===")
    print("range =", start, "to", end)
    print("weekdays =", len(dates))
    print("app_sha256 =", fingerprint)
    print("seeded_old_results = 0")
    print("output =", output)
    print()

    for index, trade_date in enumerate(dates, 1):
        row = run_one(app_module, trade_date, fingerprint)
        rows.append(row)
        checkpoint(output, rows)
        print(
            f"{index}/{len(dates)}",
            trade_date,
            "|",
            row["status"],
            "|",
            (row["summary"] or row["error"])[:170],
            flush=True,
        )
        time.sleep(max(0.0, args.delay))

    ok_rows = [row for row in rows if row["status"] == "OK"]
    error_rows = [row for row in rows if row["status"] == "ERROR"]
    total_trades = 0
    active_days = 0
    total_pnl = 0.0
    monthly: Dict[str, Dict[str, float]] = {}

    for row in ok_rows:
        match = SUMMARY_RE.search(row["summary"])
        if not match:
            continue
        trades = int(match.group(1))
        pnl = float(match.group(2))
        total_trades += trades
        total_pnl += pnl
        if trades > 0:
            active_days += 1

        month = row["date"][:7]
        item = monthly.setdefault(
            month,
            {"days": 0, "active_days": 0, "trades": 0, "pnl": 0.0},
        )
        item["days"] += 1
        item["active_days"] += 1 if trades > 0 else 0
        item["trades"] += trades
        item["pnl"] += pnl

    result_days = len(ok_rows)
    trades_per_result_day = total_trades / result_days if result_days else 0.0
    active_day_rate = active_days / result_days if result_days else 0.0

    enough_frequency = bool(
        result_days >= 40
        and total_trades >= 20
        and active_days >= 12
        and trades_per_result_day >= 0.30
    )

    print()
    print("=== FREQUENCY PILOT RESULT ===")
    print("result_days =", result_days)
    print("error_days =", len(error_rows))
    print("active_days =", active_days)
    print("active_day_rate =", f"{active_day_rate * 100:.2f}%")
    print("total_trades =", total_trades)
    print("trades_per_result_day =", f"{trades_per_result_day:.3f}")
    print("total_pnl =", f"{total_pnl:.2f}")
    print()
    print("=== MONTHLY ===")
    for month, item in sorted(monthly.items()):
        print(
            month,
            "| days =", int(item["days"]),
            "| active =", int(item["active_days"]),
            "| trades =", int(item["trades"]),
            "| pnl =", f"{item['pnl']:.2f}",
        )
    print()
    print("frequency_gate =", "PASS" if enough_frequency else "FAIL")
    print("two_year_run =", "ALLOWED" if enough_frequency else "HOLD")
    print("training = NOT RUN")
    print("paper = BLOCKED")
    print("live = BLOCKED")
    print("server/orders = UNCHANGED")
    return 0 if enough_frequency else 3


if __name__ == "__main__":
    raise SystemExit(main())
