"""Exact trade-sequence diagnostics for Jan-Jun 2026 backtest reports.

Reads only backtest_jan_to_jun_2026.csv. It parses the human-readable TRADES
section, verifies per-day net P&L against the summary, and compares simple
risk policies such as max-one-trade and stop-after-first-loss.

Safety: does not import app.py and cannot place/modify/cancel orders.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SOURCE = Path("backtest_jan_to_jun_2026.csv")
OUT_DIR = Path("data/ml_models/jan_jun_trade_sequence")
TRADES_CSV = OUT_DIR / "parsed_trades.csv"
POLICIES_CSV = OUT_DIR / "policy_comparison.csv"
REPORT_JSON = OUT_DIR / "trade_sequence_report.json"

SUMMARY_RE = re.compile(
    r"Trades\s+(\d+)\s*\|\s*P&L\s+([-+]?\d+(?:\.\d+)?)",
    re.I,
)
TRADE_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\s*->\s*"
    r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\s*\|",
)
NUMBER_RE = r"([-+]?\d+(?:\.\d+)?)"


def fnum(text: str, label: str) -> Optional[float]:
    match = re.search(rf"\b{re.escape(label)}\s+{NUMBER_RE}", text, re.I)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except Exception:
        return None
    return value if math.isfinite(value) else None


def canonical_reason(text: str) -> str:
    upper = text.upper()
    if "BT TARGET" in upper:
        return "TARGET"
    if "BT PROFIT FLOOR" in upper:
        return "PROFIT_FLOOR"
    if "BT SL/TRAIL HIT" in upper:
        return "SL_TRAIL_HIT"
    if "MOMENTUM COLLAPSE" in upper:
        return "MOMENTUM_COLLAPSE"
    if "VWAP" in upper and "BREAK" in upper:
        return "VWAP_BREAK"
    if "SUPERTREND" in upper and "FLIP" in upper:
        return "SUPERTREND_FLIP"
    if "TIME" in upper and "EXIT" in upper:
        return "TIME_EXIT"
    return "OTHER"


def parse_trade_line(line: str, index: int) -> Optional[Dict[str, Any]]:
    match = TRADE_LINE_RE.match(line.strip())
    if not match:
        return None

    parts = [part.strip() for part in line.split("|")]
    if len(parts) < 9:
        return None

    side = parts[2].upper() if len(parts) > 2 else "UNKNOWN"
    symbol = parts[3] if len(parts) > 3 else ""
    entry = fnum(line, "Entry")
    exit_price = fnum(line, "Exit")
    qty = fnum(line, "Qty")
    gross = fnum(line, "Gross")
    charges = fnum(line, "Charges")
    net = fnum(line, "Net")
    if net is None:
        return None

    entry_dt = datetime.fromisoformat(f"{match.group(1)} {match.group(2)}")
    exit_dt = datetime.fromisoformat(f"{match.group(3)} {match.group(4)}")
    reason_text = " | ".join(parts[9:]) if len(parts) > 9 else parts[-1]

    momentum = None
    momentum_matches = re.findall(r"\bMomentum(?:\s+score)?\s+([0-9]+(?:\.\d+)?)", line, re.I)
    if momentum_matches:
        momentum = float(momentum_matches[-1])

    return {
        "date": match.group(1),
        "trade_index": index,
        "entry_time": match.group(2),
        "exit_time": match.group(4),
        "duration_seconds": int((exit_dt - entry_dt).total_seconds()),
        "side": side,
        "symbol": symbol,
        "entry_price": entry,
        "exit_price": exit_price,
        "qty": int(qty) if qty is not None else "",
        "gross": gross,
        "charges": charges,
        "net": net,
        "result": "WIN" if net > 0 else "LOSS" if net < 0 else "FLAT",
        "reason": canonical_reason(reason_text),
        "reason_text": reason_text,
        "momentum": "" if momentum is None else momentum,
        "raw": line.strip(),
    }


def max_drawdown(daily_pnl: List[Tuple[str, float]]) -> Tuple[float, str]:
    running = 0.0
    peak = 0.0
    worst = 0.0
    worst_date = ""
    for trade_date, pnl in daily_pnl:
        running += pnl
        peak = max(peak, running)
        drawdown = peak - running
        if drawdown > worst:
            worst = drawdown
            worst_date = trade_date
    return worst, worst_date


def policy_actual(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return list(trades)


def policy_max_n(trades: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    return list(trades[:n])


def policy_stop_after_first_loss(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    chosen: List[Dict[str, Any]] = []
    for trade in trades:
        chosen.append(trade)
        if trade["net"] < 0:
            break
    return chosen


def policy_stop_after_two_losses(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    chosen: List[Dict[str, Any]] = []
    losses = 0
    for trade in trades:
        chosen.append(trade)
        if trade["net"] < 0:
            losses += 1
            if losses >= 2:
                break
    return chosen


def policy_stop_after_first_win(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    chosen: List[Dict[str, Any]] = []
    for trade in trades:
        chosen.append(trade)
        if trade["net"] > 0:
            break
    return chosen


def policy_skip_fast_reentry(trades: List[Dict[str, Any]], minutes: int = 5) -> List[Dict[str, Any]]:
    chosen: List[Dict[str, Any]] = []
    previous_exit: Optional[datetime] = None
    for trade in trades:
        entry_dt = datetime.fromisoformat(f"{trade['date']} {trade['entry_time']}")
        if previous_exit is not None:
            gap = (entry_dt - previous_exit).total_seconds() / 60.0
            if gap <= minutes:
                continue
        chosen.append(trade)
        previous_exit = datetime.fromisoformat(f"{trade['date']} {trade['exit_time']}")
    return chosen


def summarize_policy(
    name: str,
    by_day: Dict[str, List[Dict[str, Any]]],
    selector,
) -> Dict[str, Any]:
    daily: List[Tuple[str, float]] = []
    trades = 0
    wins = 0
    losses = 0
    active_days = 0
    profit_days = 0
    loss_days = 0

    for trade_date in sorted(by_day):
        chosen = selector(by_day[trade_date])
        pnl = sum(float(item["net"]) for item in chosen)
        count = len(chosen)
        trades += count
        wins += sum(1 for item in chosen if item["net"] > 0)
        losses += sum(1 for item in chosen if item["net"] < 0)
        if count:
            active_days += 1
        if pnl > 0:
            profit_days += 1
        elif pnl < 0:
            loss_days += 1
        daily.append((trade_date, pnl))

    total_pnl = sum(pnl for _, pnl in daily)
    drawdown, drawdown_date = max_drawdown(daily)
    return {
        "policy": name,
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round((wins / trades * 100.0) if trades else 0.0, 2),
        "active_days": active_days,
        "profit_days": profit_days,
        "loss_days": loss_days,
        "profitable_day_rate": round(
            (profit_days / active_days * 100.0) if active_days else 0.0,
            2,
        ),
        "total_pnl": round(total_pnl, 2),
        "average_pnl_per_trade": round((total_pnl / trades) if trades else 0.0, 2),
        "max_drawdown": round(drawdown, 2),
        "max_drawdown_date": drawdown_date,
    }


def aggregate(trades: List[Dict[str, Any]], key: str) -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}
    )
    for trade in trades:
        name = str(trade.get(key) or "UNKNOWN")
        item = groups[name]
        item["trades"] += 1
        item["pnl"] += float(trade["net"])
        if trade["net"] > 0:
            item["wins"] += 1
        elif trade["net"] < 0:
            item["losses"] += 1
    for item in groups.values():
        item["pnl"] = round(item["pnl"], 2)
        item["win_rate"] = round(
            (item["wins"] / item["trades"] * 100.0) if item["trades"] else 0.0,
            2,
        )
    return dict(groups)


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

    parsed: List[Dict[str, Any]] = []
    by_day: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    validation_errors: List[Dict[str, Any]] = []
    ok_days = 0

    for row in source_rows:
        if str(row.get("status") or "") != "OK":
            continue
        summary = str(row.get("summary") or "")
        summary_match = SUMMARY_RE.search(summary)
        if not summary_match:
            continue

        trade_date = str(row.get("date") or "")
        expected_count = int(summary_match.group(1))
        expected_pnl = float(summary_match.group(2))
        report = str(row.get("report") or "")

        day_trades: List[Dict[str, Any]] = []
        for line in report.splitlines():
            if not TRADE_LINE_RE.match(line.strip()):
                continue
            trade = parse_trade_line(line, len(day_trades) + 1)
            if trade:
                day_trades.append(trade)

        actual_pnl = round(sum(float(item["net"]) for item in day_trades), 2)
        count_ok = len(day_trades) == expected_count
        pnl_ok = abs(actual_pnl - expected_pnl) <= 0.05
        if not count_ok or not pnl_ok:
            validation_errors.append(
                {
                    "date": trade_date,
                    "expected_count": expected_count,
                    "parsed_count": len(day_trades),
                    "expected_pnl": expected_pnl,
                    "parsed_pnl": actual_pnl,
                }
            )
        else:
            ok_days += 1

        parsed.extend(day_trades)
        by_day[trade_date] = day_trades

    policies = [
        summarize_policy("ACTUAL", by_day, policy_actual),
        summarize_policy("MAX_1_TRADE", by_day, lambda trades: policy_max_n(trades, 1)),
        summarize_policy("MAX_2_TRADES", by_day, lambda trades: policy_max_n(trades, 2)),
        summarize_policy("STOP_AFTER_FIRST_LOSS", by_day, policy_stop_after_first_loss),
        summarize_policy("STOP_AFTER_TWO_LOSSES", by_day, policy_stop_after_two_losses),
        summarize_policy("STOP_AFTER_FIRST_WIN", by_day, policy_stop_after_first_win),
        summarize_policy(
            "SKIP_REENTRY_WITHIN_5_MIN",
            by_day,
            lambda trades: policy_skip_fast_reentry(trades, 5),
        ),
    ]

    by_index = aggregate(parsed, "trade_index")
    by_side = aggregate(parsed, "side")
    by_reason = aggregate(parsed, "reason")

    for trade in parsed:
        trade["entry_hour"] = trade["entry_time"][:2]
    by_entry_hour = aggregate(parsed, "entry_hour")

    report = {
        "source": str(SOURCE),
        "parsed_trades": len(parsed),
        "days_validated": ok_days,
        "validation_errors": validation_errors,
        "policies": policies,
        "by_trade_index": by_index,
        "by_side": by_side,
        "by_reason": by_reason,
        "by_entry_hour": by_entry_hour,
        "paper": "BLOCKED",
        "live": "BLOCKED",
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    trade_columns = [
        "date",
        "trade_index",
        "entry_time",
        "exit_time",
        "duration_seconds",
        "side",
        "symbol",
        "entry_price",
        "exit_price",
        "qty",
        "gross",
        "charges",
        "net",
        "result",
        "reason",
        "momentum",
        "reason_text",
    ]
    policy_columns = [
        "policy",
        "trades",
        "wins",
        "losses",
        "win_rate",
        "active_days",
        "profit_days",
        "loss_days",
        "profitable_day_rate",
        "total_pnl",
        "average_pnl_per_trade",
        "max_drawdown",
        "max_drawdown_date",
    ]
    write_csv(TRADES_CSV, parsed, trade_columns)
    write_csv(POLICIES_CSV, policies, policy_columns)

    print("=== EXACT TRADE-SEQUENCE ANALYSIS ===")
    print("parsed_trades =", len(parsed))
    print("days_validated =", ok_days)
    print("validation_errors =", len(validation_errors))
    if validation_errors:
        for item in validation_errors[:10]:
            print("VALIDATION_ERROR", item)

    print()
    print("=== POLICY COMPARISON ===")
    for item in policies:
        print(
            item["policy"],
            "| trades =", item["trades"],
            "| W/L =", f"{item['wins']}/{item['losses']}",
            "| win_rate =", f"{item['win_rate']:.2f}%",
            "| profit/loss days =", f"{item['profit_days']}/{item['loss_days']}",
            "| pnl =", f"{item['total_pnl']:.2f}",
            "| max_dd =", f"{item['max_drawdown']:.2f}",
        )

    print()
    print("=== P&L BY TRADE INDEX ===")
    for key in sorted(by_index, key=lambda value: int(value)):
        item = by_index[key]
        print(
            "trade", key,
            "| count =", item["trades"],
            "| W/L =", f"{item['wins']}/{item['losses']}",
            "| win_rate =", f"{item['win_rate']:.2f}%",
            "| pnl =", f"{item['pnl']:.2f}",
        )

    print()
    print("=== SIDE SUMMARY ===")
    for key in sorted(by_side):
        item = by_side[key]
        print(
            key,
            "| trades =", item["trades"],
            "| W/L =", f"{item['wins']}/{item['losses']}",
            "| win_rate =", f"{item['win_rate']:.2f}%",
            "| pnl =", f"{item['pnl']:.2f}",
        )

    print()
    print("=== EXIT REASONS ===")
    for key, item in sorted(by_reason.items(), key=lambda pair: pair[1]["pnl"]):
        print(
            key,
            "| trades =", item["trades"],
            "| W/L =", f"{item['wins']}/{item['losses']}",
            "| pnl =", f"{item['pnl']:.2f}",
        )

    print()
    print("trades_csv =", TRADES_CSV)
    print("policies_csv =", POLICIES_CSV)
    print("report_json =", REPORT_JSON)
    print("paper = BLOCKED")
    print("live = BLOCKED")
    print("server/orders = UNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
