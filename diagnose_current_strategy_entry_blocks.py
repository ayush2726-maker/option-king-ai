"""Compact diagnostics for zero-trade current-strategy backtests.

Runs the existing REALISTIC backtest for a short date range, captures verbose
stdout/stderr in memory one date at a time, and aggregates why candidate CE/PE
signals were blocked. It does not modify app.py or place/modify/cancel orders.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SUMMARY_RE = re.compile(
    r"Trades\s+(\d+)\s*\|\s*P&L\s+([-+]?\d+(?:\.\d+)?)",
    re.I,
)
BLOCK_RE = re.compile(
    r"TQU BLOCKED\s+(CE|PE)\s*\|\s*([^:|]+)(?:\s+blocked)?\s*:\s*(.*)",
    re.I,
)
SCORE_RE = re.compile(r"score\s*=\s*([-+]?\d+(?:\.\d+)?)", re.I)
NEED_SCORE_RE = re.compile(r"need\s*>\s*([-+]?\d+(?:\.\d+)?)", re.I)
VOL_RE = re.compile(r"vol\s*=\s*([-+]?\d+(?:\.\d+)?)x", re.I)
NEED_VOL_RE = re.compile(r"vol[^|]*need\s*>\s*([-+]?\d+(?:\.\d+)?)x", re.I)
CORE_RE = re.compile(r"core\s*=\s*(\d+)\s*/\s*(\d+)", re.I)
WEIGHTED_RE = re.compile(r"weighted\s*=\s*([-+]?\d+(?:\.\d+)?)", re.I)
REGIME_RE = re.compile(r"regime\s*=\s*([A-Z_]+)", re.I)
ADX_RE = re.compile(r"ADX DEBUG.*?adx\s*=\s*([-+]?\d+(?:\.\d+)?)", re.I)
CANDIDATE_RE = re.compile(r"BT VOL/CORE FILL.*?\|\s*(CE|PE)\s*\|", re.I)


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def weekdays(start: date, end: date) -> Iterable[str]:
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current.isoformat()
        current += timedelta(days=1)


def first_float(pattern: re.Pattern[str], text: str) -> Optional[float]:
    match = pattern.search(text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def load_app():
    with open("/dev/null", "w") as devnull:
        with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
            import app
    return app


def get_summary_and_report(result: Any) -> tuple[str, str]:
    if isinstance(result, dict):
        return str(result.get("summary") or ""), str(result.get("report") or "")
    if isinstance(result, tuple):
        summary = str(result[0] if len(result) > 0 else "")
        report = str(result[1] if len(result) > 1 else "")
        return summary, report
    return str(result), ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-07-01")
    parser.add_argument("--end", default="2025-07-14")
    args = parser.parse_args()

    start = parse_date(args.start)
    end = parse_date(args.end)
    if end < start:
        raise SystemExit("end date must be on or after start date")

    app_module = load_app()
    dates = list(weekdays(start, end))

    block_reason_counts: Counter[str] = Counter()
    regime_counts: Counter[str] = Counter()
    side_blocks: Counter[str] = Counter()
    candidate_counts: Counter[str] = Counter()
    daily_rows: List[Dict[str, Any]] = []
    all_scores: List[float] = []
    all_needed_scores: List[float] = []
    all_volumes: List[float] = []
    all_needed_volumes: List[float] = []
    all_weighted: List[float] = []
    all_adx: List[float] = []
    near_score_blocks = 0
    score_pass_blocks = 0
    volume_fail_blocks = 0
    core_fail_blocks = 0

    print("=== CURRENT STRATEGY ENTRY-BLOCK DIAGNOSTIC ===")
    print("range =", start.isoformat(), "to", end.isoformat())
    print("dates =", len(dates))
    print()

    for trade_date in dates:
        captured_out = io.StringIO()
        captured_err = io.StringIO()

        try:
            with contextlib.redirect_stdout(captured_out), contextlib.redirect_stderr(captured_err):
                result = app_module.run_mobile_backtest(
                    {"mode": "REALISTIC", "date": trade_date}
                )
            summary, report = get_summary_and_report(result)
            raw = captured_out.getvalue() + "\n" + captured_err.getvalue()
        except Exception as exc:
            daily_rows.append(
                {
                    "date": trade_date,
                    "status": "ERROR",
                    "trades": 0,
                    "blocks": 0,
                    "candidates": 0,
                    "max_score": "",
                    "max_weighted": "",
                    "max_adx": "",
                    "summary": f"{type(exc).__name__}: {str(exc)[:300]}",
                }
            )
            print(trade_date, "| ERROR |", type(exc).__name__, str(exc)[:180])
            continue

        summary_match = SUMMARY_RE.search(summary)
        trades = int(summary_match.group(1)) if summary_match else 0

        day_blocks = 0
        day_candidates = 0
        day_scores: List[float] = []
        day_weighted: List[float] = []
        day_adx: List[float] = []

        for line in raw.splitlines():
            candidate_match = CANDIDATE_RE.search(line)
            if candidate_match:
                side = candidate_match.group(1).upper()
                candidate_counts[side] += 1
                day_candidates += 1

            adx = first_float(ADX_RE, line)
            if adx is not None:
                all_adx.append(adx)
                day_adx.append(adx)

            block_match = BLOCK_RE.search(line)
            if not block_match:
                continue

            day_blocks += 1
            side = block_match.group(1).upper()
            reason = block_match.group(2).strip().upper().replace(" ", "_")
            detail = block_match.group(3)

            side_blocks[side] += 1
            block_reason_counts[reason] += 1

            regime_match = REGIME_RE.search(detail)
            if regime_match:
                regime_counts[regime_match.group(1).upper()] += 1

            score = first_float(SCORE_RE, detail)
            need_score = first_float(NEED_SCORE_RE, detail)
            volume = first_float(VOL_RE, detail)
            need_volume = first_float(NEED_VOL_RE, detail)
            weighted = first_float(WEIGHTED_RE, detail)
            core_match = CORE_RE.search(detail)

            if score is not None:
                all_scores.append(score)
                day_scores.append(score)
            if need_score is not None:
                all_needed_scores.append(need_score)
            if volume is not None:
                all_volumes.append(volume)
            if need_volume is not None:
                all_needed_volumes.append(need_volume)
            if weighted is not None:
                all_weighted.append(weighted)
                day_weighted.append(weighted)

            if score is not None and need_score is not None:
                if score >= need_score:
                    score_pass_blocks += 1
                elif score >= need_score - 5:
                    near_score_blocks += 1

            if volume is not None and need_volume is not None and volume < need_volume:
                volume_fail_blocks += 1

            if core_match:
                core_value = int(core_match.group(1))
                core_total = int(core_match.group(2))
                if core_value < max(1, core_total - 1):
                    core_fail_blocks += 1

        candles = ""
        candle_match = re.search(r"\bCandles:\s*(\d+)", report, re.I)
        if candle_match:
            candles = candle_match.group(1)

        row = {
            "date": trade_date,
            "status": "OK",
            "trades": trades,
            "blocks": day_blocks,
            "candidates": day_candidates,
            "max_score": max(day_scores) if day_scores else "",
            "max_weighted": max(day_weighted) if day_weighted else "",
            "max_adx": max(day_adx) if day_adx else "",
            "candles": candles,
            "summary": summary,
        }
        daily_rows.append(row)

        print(
            trade_date,
            "| trades =", trades,
            "| candidates =", day_candidates,
            "| blocks =", day_blocks,
            "| max_score =", row["max_score"],
            "| max_adx =", row["max_adx"],
            "| candles =", candles,
        )

    total_trades = sum(int(row.get("trades") or 0) for row in daily_rows)
    total_blocks = sum(int(row.get("blocks") or 0) for row in daily_rows)
    total_candidates = sum(int(row.get("candidates") or 0) for row in daily_rows)
    ok_days = sum(1 for row in daily_rows if row.get("status") == "OK")
    active_days = sum(1 for row in daily_rows if int(row.get("trades") or 0) > 0)

    print()
    print("=== COMPACT DIAGNOSIS ===")
    print("ok_days =", ok_days)
    print("active_days =", active_days)
    print("total_trades =", total_trades)
    print("candidate_lines =", total_candidates)
    print("blocked_lines =", total_blocks)
    print("side_blocks =", dict(side_blocks))
    print("block_reasons =", dict(block_reason_counts.most_common()))
    print("regimes =", dict(regime_counts.most_common()))
    print("score_pass_but_still_blocked =", score_pass_blocks)
    print("within_5_points_of_score_gate =", near_score_blocks)
    print("volume_fail_blocks =", volume_fail_blocks)
    print("core_fail_blocks =", core_fail_blocks)

    if all_scores:
        print(
            "score_range =",
            f"{min(all_scores):.1f}",
            "to",
            f"{max(all_scores):.1f}",
            "| average =",
            f"{sum(all_scores) / len(all_scores):.2f}",
        )
    if all_needed_scores:
        print(
            "required_score_range =",
            f"{min(all_needed_scores):.1f}",
            "to",
            f"{max(all_needed_scores):.1f}",
        )
    if all_volumes:
        print(
            "volume_range =",
            f"{min(all_volumes):.2f}x",
            "to",
            f"{max(all_volumes):.2f}x",
        )
    if all_needed_volumes:
        print(
            "required_volume_range =",
            f"{min(all_needed_volumes):.2f}x",
            "to",
            f"{max(all_needed_volumes):.2f}x",
        )
    if all_adx:
        print(
            "adx_range =",
            f"{min(all_adx):.2f}",
            "to",
            f"{max(all_adx):.2f}",
            "| average =",
            f"{sum(all_adx) / len(all_adx):.2f}",
        )

    if total_trades == 0:
        print("frequency_status = ZERO_TRADE_CONFIRMED")
        print("two_year_run = HOLD")
    else:
        print("frequency_status = SOME_TRADES_FOUND")
        print("two_year_run = STILL_HOLD_UNTIL_PILOT_COMPLETES")

    print("strategy_changes = NOT APPLIED")
    print("app.py = UNCHANGED")
    print("paper = BLOCKED")
    print("live = BLOCKED")
    print("server/orders = UNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
