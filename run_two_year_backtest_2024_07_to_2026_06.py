"""Resumable two-year REALISTIC backtest runner.

Range: 2024-07-01 through 2026-06-30.

Safety: imports the existing app backtest function only. It does not place,
modify, or cancel live orders. Results are checkpointed after every date.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict

START = date(2024, 7, 1)
END = date(2026, 6, 30)
OUT = Path("backtest_two_year_2024_07_to_2026_06.csv")
SEED = Path("backtest_jan_to_jun_2026.csv")
FIELDS = ["date", "status", "summary", "stats", "report", "error"]
SMOKE_DATES = ["2024-07-01", "2025-01-02", "2025-12-31"]


def read_rows(path: Path) -> Dict[str, Dict[str, str]]:
    rows: Dict[str, Dict[str, str]] = {}
    if not path.exists() or path.stat().st_size == 0:
        return rows

    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            trade_date = str(row.get("date") or "")
            if trade_date:
                rows[trade_date] = {
                    field: str(row.get(field) or "")
                    for field in FIELDS
                }
    return rows


def checkpoint(rows: Dict[str, Dict[str, str]]) -> None:
    temporary = OUT.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for trade_date in sorted(rows):
            writer.writerow(rows[trade_date])
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, OUT)


def normalize_result(trade_date: str, result: Any) -> Dict[str, str]:
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
                "GROSS P&L",
                "NET P&L",
                "TRADES:",
                "WINS:",
                "LOSSES:",
                "STOP REASON",
                "->",
                "AI TRADE QUALITY",
                "NO DATA",
                "NO TRADE",
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
    }


def load_app():
    with open("/dev/null", "w") as devnull:
        with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
            import app
    return app


def run_one(app_module, trade_date: str) -> Dict[str, str]:
    try:
        with open("/dev/null", "w") as devnull:
            with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                result = app_module.run_mobile_backtest(
                    {"mode": "REALISTIC", "date": trade_date}
                )
        return normalize_result(trade_date, result)
    except Exception as exc:
        return {
            "date": trade_date,
            "status": "ERROR",
            "summary": "",
            "stats": "",
            "report": "",
            "error": f"{type(exc).__name__}: {str(exc)[:700]}",
        }


def iter_weekdays():
    current = START
    while current <= END:
        if current.weekday() < 5:
            yield current.isoformat()
        current += timedelta(days=1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--delay", type=float, default=0.8)
    args = parser.parse_args()

    app_module = load_app()

    if args.smoke:
        print("=== TWO-YEAR BACKTEST SMOKE TEST ===")
        failures = 0
        for trade_date in SMOKE_DATES:
            row = run_one(app_module, trade_date)
            if row["status"] == "OK":
                print(trade_date, "| OK |", row["summary"][:180])
            else:
                failures += 1
                print(trade_date, "| ERROR |", row["error"][:220])
            time.sleep(max(0.0, args.delay))
        print("smoke_failures =", failures)
        print("server/orders = UNCHANGED")
        return 0 if failures == 0 else 2

    rows = read_rows(OUT)

    seeded = 0
    if SEED.exists():
        for trade_date, row in read_rows(SEED).items():
            if START.isoformat() <= trade_date <= END.isoformat() and trade_date not in rows:
                rows[trade_date] = row
                seeded += 1
        if seeded:
            checkpoint(rows)

    processed = 0
    skipped = 0
    ok = 0
    errors = 0
    dates = list(iter_weekdays())

    print("=== TWO-YEAR REALISTIC BACKTEST ===")
    print("range =", START.isoformat(), "to", END.isoformat())
    print("weekdays =", len(dates))
    print("seeded_from_jan_jun_2026 =", seeded)
    print("existing_rows =", len(rows))
    print("output =", OUT)
    print()

    for index, trade_date in enumerate(dates, 1):
        existing = rows.get(trade_date)
        if existing and (existing.get("status") == "OK" or not args.retry_errors):
            skipped += 1
            continue

        row = run_one(app_module, trade_date)
        rows[trade_date] = row
        checkpoint(rows)
        processed += 1

        if row["status"] == "OK":
            ok += 1
            print(
                f"{index}/{len(dates)}",
                trade_date,
                "| OK |",
                row["summary"][:150],
                flush=True,
            )
        else:
            errors += 1
            print(
                f"{index}/{len(dates)}",
                trade_date,
                "| ERROR |",
                row["error"][:180],
                flush=True,
            )

        time.sleep(max(0.0, args.delay))

    final_rows = read_rows(OUT)
    final_ok = sum(1 for row in final_rows.values() if row["status"] == "OK")
    final_errors = sum(1 for row in final_rows.values() if row["status"] == "ERROR")

    print()
    print("=== TWO-YEAR BACKTEST COMPLETE ===")
    print("processed_now =", processed)
    print("skipped_existing =", skipped)
    print("ok_now =", ok)
    print("errors_now =", errors)
    print("final_ok_rows =", final_ok)
    print("final_error_rows =", final_errors)
    print("csv =", OUT)
    print("paper = BLOCKED")
    print("live = BLOCKED")
    print("server/orders = UNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
