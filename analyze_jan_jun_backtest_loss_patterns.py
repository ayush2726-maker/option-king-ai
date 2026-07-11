"""Read-only Jan-Jun 2026 backtest diagnostics.

Reads backtest_jan_to_jun_2026.csv only. It does not import app.py and cannot
place/modify/cancel orders. Produces compact CSV/JSON diagnostics so strategy
changes can be based on evidence instead of guesswork.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SOURCE = Path("backtest_jan_to_jun_2026.csv")
OUT_DIR = Path("data/ml_models/jan_jun_backtest_diagnostics")
DAY_CSV = OUT_DIR / "daily_diagnostics.csv"
TRADE_CSV = OUT_DIR / "extracted_trade_records.csv"
REPORT_JSON = OUT_DIR / "diagnostic_report.json"

SUMMARY_RE = re.compile(
    r"Trades\s+(\d+)\s*\|\s*P&L\s+([-+]?\d+(?:\.\d+)?)",
    re.I,
)
SIDE_RE = re.compile(r"\b(CE|PE)\b", re.I)
TIME_RE = re.compile(r"\b([01]\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?\b")
PNL_RE = re.compile(
    r"(?:P&L|PNL|NET(?:\s+P&L)?|PROFIT|LOSS)\s*[:=|-]?\s*"
    r"(?:₹\s*)?([-+]?\d+(?:\.\d+)?)",
    re.I,
)
SCORE_RE = re.compile(
    r"(?:SCORE|CONFIDENCE)\s*[:=|-]?\s*([0-9]+(?:\.\d+)?)",
    re.I,
)

PNL_KEYS = (
    "pnl",
    "net_pnl",
    "profit_loss",
    "profit",
    "realized_pnl",
    "realised_pnl",
)
SIDE_KEYS = ("side", "option_type", "direction", "signal", "trade_side")
SYMBOL_KEYS = ("symbol", "tradingsymbol", "trading_symbol", "instrument")
REASON_KEYS = ("exit_reason", "reason", "close_reason", "status_reason")
ENTRY_TIME_KEYS = ("entry_time", "buy_time", "opened_at", "entry_timestamp")
EXIT_TIME_KEYS = ("exit_time", "sell_time", "closed_at", "exit_timestamp")
SCORE_KEYS = ("score", "confidence", "entry_score", "signal_score")


def finite_float(value: Any) -> Optional[float]:
    try:
        number = float(str(value).replace(",", "").replace("₹", "").strip())
    except Exception:
        return None
    return number if math.isfinite(number) else None


def first_value(data: Dict[str, Any], keys: Iterable[str]) -> Any:
    lowered = {str(key).lower(): value for key, value in data.items()}
    for key in keys:
        if key in lowered and lowered[key] not in (None, ""):
            return lowered[key]
    return None


def normalize_side(value: Any) -> str:
    text = str(value or "").upper()
    match = SIDE_RE.search(text)
    return match.group(1).upper() if match else "UNKNOWN"


def normalize_time(value: Any) -> str:
    text = str(value or "")
    match = TIME_RE.search(text)
    return f"{match.group(1)}:{match.group(2)}" if match else ""


def candidate_trade_dict(data: Dict[str, Any]) -> bool:
    keys = {str(key).lower() for key in data}
    has_pnl = bool(keys.intersection(PNL_KEYS))
    has_identity = bool(
        keys.intersection(SIDE_KEYS)
        or keys.intersection(SYMBOL_KEYS)
        or keys.intersection(ENTRY_TIME_KEYS)
        or keys.intersection(EXIT_TIME_KEYS)
    )
    return has_pnl and has_identity


def walk_trade_dicts(obj: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(obj, dict):
        if candidate_trade_dict(obj):
            yield obj
        for value in obj.values():
            yield from walk_trade_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk_trade_dicts(value)


def extract_trade_from_dict(trade_date: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    pnl = finite_float(first_value(data, PNL_KEYS))
    if pnl is None:
        return None

    symbol = str(first_value(data, SYMBOL_KEYS) or "")
    side = normalize_side(first_value(data, SIDE_KEYS) or symbol)
    reason = str(first_value(data, REASON_KEYS) or "").strip()
    entry_time = normalize_time(first_value(data, ENTRY_TIME_KEYS))
    exit_time = normalize_time(first_value(data, EXIT_TIME_KEYS))
    score = finite_float(first_value(data, SCORE_KEYS))

    return {
        "date": trade_date,
        "source": "stats",
        "side": side,
        "symbol": symbol,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "exit_reason": reason,
        "score": "" if score is None else score,
        "pnl": pnl,
        "raw": json.dumps(data, ensure_ascii=False, default=str)[:1200],
    }


def extract_report_trades(trade_date: str, report: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for line in report.splitlines():
        upper = line.upper()
        if "EXIT" not in upper and "CLOSED" not in upper and "BOOK" not in upper:
            continue

        pnl_match = PNL_RE.search(line)
        if not pnl_match:
            continue

        pnl = finite_float(pnl_match.group(1))
        if pnl is None:
            continue

        side_match = SIDE_RE.search(line)
        time_matches = TIME_RE.findall(line)
        score_match = SCORE_RE.search(line)

        reason = ""
        reason_match = re.search(
            r"(?:REASON|EXIT)\s*[:=|-]\s*([^|]+)",
            line,
            re.I,
        )
        if reason_match:
            reason = reason_match.group(1).strip()

        records.append(
            {
                "date": trade_date,
                "source": "report",
                "side": side_match.group(1).upper() if side_match else "UNKNOWN",
                "symbol": "",
                "entry_time": "",
                "exit_time": (
                    f"{time_matches[-1][0]}:{time_matches[-1][1]}"
                    if time_matches else ""
                ),
                "exit_reason": reason,
                "score": (
                    finite_float(score_match.group(1))
                    if score_match else ""
                ),
                "pnl": pnl,
                "raw": line.strip()[:1200],
            }
        )
    return records


def longest_streak(days: List[Dict[str, Any]], predicate) -> Tuple[int, str, str]:
    best_length = 0
    best_start = ""
    best_end = ""
    current_length = 0
    current_start = ""

    for row in days:
        if predicate(row):
            if current_length == 0:
                current_start = row["date"]
            current_length += 1
            if current_length > best_length:
                best_length = current_length
                best_start = current_start
                best_end = row["date"]
        else:
            current_length = 0
            current_start = ""

    return best_length, best_start, best_end


def write_csv(path: Path, rows: List[Dict[str, Any]], columns: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"Missing source file: {SOURCE}")

    with SOURCE.open("r", encoding="utf-8", newline="") as handle:
        source_rows = list(csv.DictReader(handle))

    days: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    trade_records: List[Dict[str, Any]] = []

    for row in source_rows:
        trade_date = str(row.get("date") or "")
        status = str(row.get("status") or "")
        if status != "OK":
            errors.append({"date": trade_date, "error": str(row.get("error") or "")})
            continue

        summary = str(row.get("summary") or "")
        match = SUMMARY_RE.search(summary)
        if not match:
            errors.append({"date": trade_date, "error": "summary_parse_failed"})
            continue

        trades = int(match.group(1))
        pnl = float(match.group(2))
        day = {
            "date": trade_date,
            "month": trade_date[:7],
            "trades": trades,
            "pnl": pnl,
            "result": "PROFIT" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT",
        }
        days.append(day)

        stats_text = str(row.get("stats") or "").strip()
        stats_obj: Any = None
        if stats_text:
            try:
                stats_obj = json.loads(stats_text)
            except Exception:
                stats_obj = None

        stats_trades: List[Dict[str, Any]] = []
        if stats_obj is not None:
            for item in walk_trade_dicts(stats_obj):
                extracted = extract_trade_from_dict(trade_date, item)
                if extracted:
                    stats_trades.append(extracted)

        if stats_trades:
            trade_records.extend(stats_trades)
        else:
            trade_records.extend(
                extract_report_trades(trade_date, str(row.get("report") or ""))
            )

    days.sort(key=lambda item: item["date"])

    monthly: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "days": 0,
            "active_days": 0,
            "profit_days": 0,
            "loss_days": 0,
            "no_trade_days": 0,
            "trades": 0,
            "pnl": 0.0,
        }
    )
    by_trade_count: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"days": 0, "profit_days": 0, "loss_days": 0, "pnl": 0.0}
    )

    running = 0.0
    peak = 0.0
    max_drawdown = 0.0
    max_drawdown_date = ""

    for day in days:
        month = monthly[day["month"]]
        month["days"] += 1
        month["trades"] += day["trades"]
        month["pnl"] += day["pnl"]
        if day["trades"] == 0:
            month["no_trade_days"] += 1
        else:
            month["active_days"] += 1
            if day["pnl"] > 0:
                month["profit_days"] += 1
            elif day["pnl"] < 0:
                month["loss_days"] += 1

        bucket = str(day["trades"]) if day["trades"] < 4 else "4+"
        item = by_trade_count[bucket]
        item["days"] += 1
        item["pnl"] += day["pnl"]
        if day["pnl"] > 0:
            item["profit_days"] += 1
        elif day["pnl"] < 0:
            item["loss_days"] += 1

        running += day["pnl"]
        peak = max(peak, running)
        drawdown = peak - running
        if drawdown > max_drawdown:
            max_drawdown = drawdown
            max_drawdown_date = day["date"]

    loss_streak = longest_streak(days, lambda item: item["pnl"] < 0)
    non_profit_streak = longest_streak(days, lambda item: item["pnl"] <= 0)

    top_losses = sorted(days, key=lambda item: item["pnl"])[:12]
    top_profits = sorted(days, key=lambda item: item["pnl"], reverse=True)[:8]

    side_stats: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}
    )
    reason_stats: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}
    )
    exit_hour_stats: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}
    )

    for trade in trade_records:
        pnl = finite_float(trade.get("pnl"))
        if pnl is None:
            continue

        side = normalize_side(trade.get("side"))
        reason = str(trade.get("exit_reason") or "UNKNOWN").strip().upper() or "UNKNOWN"
        hour = str(trade.get("exit_time") or "")[:2] or "UNKNOWN"

        for group, key in (
            (side_stats, side),
            (reason_stats, reason[:80]),
            (exit_hour_stats, hour),
        ):
            stats = group[key]
            stats["trades"] += 1
            stats["pnl"] += pnl
            if pnl > 0:
                stats["wins"] += 1
            elif pnl < 0:
                stats["losses"] += 1

    day_columns = ["date", "month", "trades", "pnl", "result"]
    trade_columns = [
        "date",
        "source",
        "side",
        "symbol",
        "entry_time",
        "exit_time",
        "exit_reason",
        "score",
        "pnl",
        "raw",
    ]
    write_csv(DAY_CSV, days, day_columns)
    write_csv(TRADE_CSV, trade_records, trade_columns)

    total_pnl = sum(item["pnl"] for item in days)
    total_trades = sum(item["trades"] for item in days)
    active_days = [item for item in days if item["trades"] > 0]

    report = {
        "source": str(SOURCE),
        "result_days": len(days),
        "error_dates": errors,
        "total_trades": total_trades,
        "total_pnl": round(total_pnl, 2),
        "active_days": len(active_days),
        "profit_days": sum(1 for item in active_days if item["pnl"] > 0),
        "loss_days": sum(1 for item in active_days if item["pnl"] < 0),
        "max_cumulative_daily_drawdown": round(max_drawdown, 2),
        "max_drawdown_date": max_drawdown_date,
        "longest_loss_streak": {
            "days": loss_streak[0],
            "from": loss_streak[1],
            "to": loss_streak[2],
        },
        "longest_non_profit_streak": {
            "days": non_profit_streak[0],
            "from": non_profit_streak[1],
            "to": non_profit_streak[2],
        },
        "monthly": {key: value for key, value in sorted(monthly.items())},
        "by_trade_count": {key: value for key, value in sorted(by_trade_count.items())},
        "top_losses": top_losses,
        "top_profits": top_profits,
        "trade_records_extracted": len(trade_records),
        "side_stats": dict(side_stats),
        "exit_reason_stats": dict(reason_stats),
        "exit_hour_stats": dict(exit_hour_stats),
        "paper": "BLOCKED",
        "live": "BLOCKED",
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print("=== JAN-JUNE LOSS DIAGNOSTICS ===")
    print("result_days =", len(days))
    print("total_trades =", total_trades)
    print("total_pnl =", f"{total_pnl:.2f}")
    print("max_cumulative_daily_drawdown =", f"{max_drawdown:.2f}")
    print("max_drawdown_date =", max_drawdown_date)
    print(
        "longest_loss_streak =",
        loss_streak[0],
        loss_streak[1],
        "to",
        loss_streak[2],
    )
    print("trade_records_extracted =", len(trade_records))

    print()
    print("=== P&L BY TRADES PER DAY ===")
    for bucket in ("0", "1", "2", "3", "4+"):
        if bucket not in by_trade_count:
            continue
        item = by_trade_count[bucket]
        print(
            bucket,
            "trades/day | days =", item["days"],
            "| profit/loss =", f"{item['profit_days']}/{item['loss_days']}",
            "| pnl =", f"{item['pnl']:.2f}",
        )

    print()
    print("=== TOP 8 LOSS DAYS ===")
    for item in top_losses[:8]:
        print(item["date"], "| trades =", item["trades"], "| pnl =", f"{item['pnl']:.2f}")

    if trade_records:
        print()
        print("=== SIDE SUMMARY ===")
        for key, item in sorted(side_stats.items()):
            print(
                key,
                "| trades =", item["trades"],
                "| wins/losses =", f"{item['wins']}/{item['losses']}",
                "| pnl =", f"{item['pnl']:.2f}",
            )

        print()
        print("=== WORST EXIT REASONS ===")
        worst_reasons = sorted(
            reason_stats.items(),
            key=lambda pair: pair[1]["pnl"],
        )[:8]
        for key, item in worst_reasons:
            print(
                key,
                "| trades =", item["trades"],
                "| pnl =", f"{item['pnl']:.2f}",
            )
    else:
        print()
        print("trade_level_detail = NOT AVAILABLE IN CURRENT CSV")
        print("next_step = detailed rerun required")

    print()
    print("daily_csv =", DAY_CSV)
    print("trade_csv =", TRADE_CSV)
    print("report_json =", REPORT_JSON)
    print("paper = BLOCKED")
    print("live = BLOCKED")
    print("server/orders = UNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
