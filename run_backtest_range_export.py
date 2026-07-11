"""Run OKAI mobile backtest over a date range and export compact ML-ready audit files.

Safety:
- imports app.py only inside an isolated worker process per date
- hard-blocks SmartAPI order methods inside each worker
- never starts the HTTP server
- captures noisy output instead of flooding the terminal
- resumes completed dates after interruption

Example:
    python -u run_backtest_range_export.py \
      --date-from 2026-01-01 --date-to 2026-06-30 --mode REALISTIC
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


DEFAULT_OUTPUT = Path("data/ml_training/backtest_jan_jun_2026")
SPOT_ROOTS = (
    Path("data/angel_cache/spot_candles"),
    Path("users/owner/data/angel_cache/spot_candles"),
)
WORKER_SENTINEL = "__OKAI_BACKTEST_WORKER_JSON__="
MAX_CAPTURE_CHARS = 200_000

ORDER_METHODS = (
    "placeOrder",
    "placeOrderFullResponse",
    "modifyOrder",
    "cancelOrder",
    "convertPosition",
    "createRule",
    "modifyRule",
    "cancelRule",
)

TRADE_HINT_KEYS = {
    "symbol",
    "tradingsymbol",
    "side",
    "signal",
    "option_type",
    "entry",
    "entry_price",
    "entry_time",
    "exit",
    "exit_price",
    "exit_time",
    "pnl",
    "profit",
    "loss",
    "qty",
    "quantity",
    "sl",
    "stop_loss",
    "target",
    "reason",
    "exit_reason",
}

SUMMARY_FIELDS = [
    "date",
    "mode",
    "status",
    "duration_seconds",
    "result_type",
    "closed_trades",
    "wins",
    "losses",
    "win_rate_percent",
    "pnl",
    "summary",
    "report_tail",
    "raw_file",
    "error",
]


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def fallback_weekdays(start: date, end: date) -> List[str]:
    result: List[str] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def discover_cached_dates(start: date, end: date) -> List[str]:
    chosen = set()
    pattern = re.compile(r"NSE_99926000_ONE_MINUTE_(\d{8})\.json$")
    for root in SPOT_ROOTS:
        if not root.exists():
            continue
        for path in root.glob("NSE_99926000_ONE_MINUTE_*.json"):
            match = pattern.search(path.name)
            if not match:
                continue
            try:
                value = datetime.strptime(match.group(1), "%Y%m%d").date()
            except Exception:
                continue
            if start <= value <= end:
                chosen.add(value.isoformat())
    return sorted(chosen)


def json_safe(value: Any, depth: int = 0) -> Any:
    if depth > 12:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {
            str(key): json_safe(item, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item, depth + 1) for item in value]

    try:
        import pandas as pd  # type: ignore

        if isinstance(value, pd.DataFrame):
            return json_safe(value.to_dict(orient="records"), depth + 1)
        if isinstance(value, pd.Series):
            return json_safe(value.to_dict(), depth + 1)
    except Exception:
        pass

    try:
        import numpy as np  # type: ignore

        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, np.ndarray):
            return json_safe(value.tolist(), depth + 1)
    except Exception:
        pass

    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def block_order_methods() -> None:
    def blocked(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("ORDER EXECUTION BLOCKED IN BACKTEST RANGE WORKER")

    classes = []
    try:
        from SmartApi import SmartConnect  # type: ignore

        classes.append(SmartConnect)
    except Exception:
        pass
    try:
        from SmartApi.smartConnect import SmartConnect as SmartConnect2  # type: ignore

        classes.append(SmartConnect2)
    except Exception:
        pass

    for cls in classes:
        for method_name in ORDER_METHODS:
            if hasattr(cls, method_name):
                try:
                    setattr(cls, method_name, blocked)
                except Exception:
                    pass


def set_safe_app_flags(app: Any) -> None:
    safe_values = {
        "running": False,
        "bot_running_lock": False,
        "AUTO_START_BOT": False,
        "LIVE_TRADING": False,
        "LIVE_TRADING_ENABLED": False,
        "ORDER_EXECUTION_ENABLED": False,
        "execution_enabled": False,
    }
    for name, value in safe_values.items():
        if hasattr(app, name):
            try:
                setattr(app, name, value)
            except Exception:
                pass


def worker(date_text: str, mode: str) -> int:
    os.environ["OKAI_BATCH_BACKTEST"] = "1"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"

    captured_out = io.StringIO()
    captured_err = io.StringIO()
    started = time.time()
    payload: Dict[str, Any]

    try:
        with contextlib.redirect_stdout(captured_out), contextlib.redirect_stderr(captured_err):
            block_order_methods()
            import app  # type: ignore

            set_safe_app_flags(app)
            function = getattr(app, "run_mobile_backtest", None)
            if not callable(function):
                raise RuntimeError("app.run_mobile_backtest is not callable")

            result = function({"mode": mode, "date": date_text})

        payload = {
            "status": "ok",
            "date": date_text,
            "mode": mode,
            "duration_seconds": round(time.time() - started, 3),
            "result_type": type(result).__name__,
            "result": json_safe(result),
            "captured_stdout": captured_out.getvalue()[-MAX_CAPTURE_CHARS:],
            "captured_stderr": captured_err.getvalue()[-MAX_CAPTURE_CHARS:],
            "orders": "BLOCKED",
        }
    except Exception as exc:
        payload = {
            "status": "error",
            "date": date_text,
            "mode": mode,
            "duration_seconds": round(time.time() - started, 3),
            "result_type": "",
            "result": None,
            "captured_stdout": captured_out.getvalue()[-MAX_CAPTURE_CHARS:],
            "captured_stderr": captured_err.getvalue()[-MAX_CAPTURE_CHARS:],
            "error": repr(exc),
            "orders": "BLOCKED",
        }

    print(WORKER_SENTINEL + json.dumps(payload, ensure_ascii=False, default=str))
    return 0 if payload["status"] == "ok" else 1


def result_sections(result: Any) -> Tuple[str, str, Any]:
    summary = ""
    report = ""
    stats: Any = {}

    if isinstance(result, dict):
        summary = str(result.get("summary") or result.get("message") or "")
        report = str(result.get("report") or result.get("details") or "")
        stats = result.get("stats") or result.get("statistics") or {}
    elif isinstance(result, list):
        if len(result) > 0:
            summary = str(result[0])
        if len(result) > 1:
            report = str(result[1])
        if len(result) > 2:
            stats = result[2]
    else:
        summary = str(result or "")

    return summary, report, stats


def flatten_scalars(value: Any, prefix: str = "", output: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if output is None:
        output = {}
    if isinstance(value, dict):
        for key, item in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            flatten_scalars(item, name, output)
    elif isinstance(value, list):
        return output
    elif value is None or isinstance(value, (str, int, float, bool)):
        output[prefix] = value
    return output


def first_numeric(flat: Dict[str, Any], names: Sequence[str]) -> Optional[float]:
    lowered = {key.lower(): value for key, value in flat.items()}
    for name in names:
        target = name.lower()
        for key, value in lowered.items():
            leaf = key.rsplit(".", 1)[-1]
            if leaf == target or key.endswith("." + target):
                try:
                    return float(str(value).replace(",", "").replace("₹", "").strip())
                except Exception:
                    continue
    return None


def regex_number(text: str, patterns: Sequence[str]) -> Optional[float]:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        try:
            return float(match.group(1).replace(",", ""))
        except Exception:
            continue
    return None


def extract_summary_row(payload: Dict[str, Any], raw_file: Path) -> Dict[str, Any]:
    result = payload.get("result")
    summary, report, stats = result_sections(result)
    flat = flatten_scalars(result)
    flat.update({f"stats.{key}": value for key, value in flatten_scalars(stats).items()})
    combined = "\n".join(
        [
            summary,
            report,
            str(payload.get("captured_stdout") or ""),
            str(payload.get("captured_stderr") or ""),
        ]
    )

    closed_trades = first_numeric(flat, ("closed_trades", "total_trades", "trades"))
    wins = first_numeric(flat, ("wins", "winning_trades", "win"))
    losses = first_numeric(flat, ("losses", "losing_trades", "loss"))
    win_rate = first_numeric(flat, ("win_rate", "win_rate_percent"))
    pnl = first_numeric(flat, ("daily_pnl", "net_pnl", "pnl", "profit_loss"))

    if closed_trades is None:
        closed_trades = regex_number(
            combined,
            (
                r"Closed\s+Trades\s*[:=]\s*(-?[0-9,.]+)",
                r"\bTrades\s*[:=]\s*(-?[0-9,.]+)",
            ),
        )
    if wins is None:
        wins = regex_number(combined, (r"\bWins?\s*[:=]\s*(-?[0-9,.]+)",))
    if losses is None:
        losses = regex_number(combined, (r"\bLoss(?:es)?\s*[:=]\s*(-?[0-9,.]+)",))
    if win_rate is None:
        win_rate = regex_number(combined, (r"Win\s*Rate\s*[:=]\s*(-?[0-9,.]+)",))
    if pnl is None:
        pnl = regex_number(
            combined,
            (
                r"(?:Daily|Net)?\s*P\s*&?\s*L\s*[:=]\s*[₹ ]*(-?[0-9,.]+)",
                r"(?:Profit|PnL)\s*[:=]\s*[₹ ]*(-?[0-9,.]+)",
            ),
        )

    def clean_count(value: Optional[float]) -> str:
        if value is None:
            return ""
        return str(int(value)) if float(value).is_integer() else str(value)

    return {
        "date": payload.get("date", ""),
        "mode": payload.get("mode", ""),
        "status": payload.get("status", ""),
        "duration_seconds": payload.get("duration_seconds", ""),
        "result_type": payload.get("result_type", ""),
        "closed_trades": clean_count(closed_trades),
        "wins": clean_count(wins),
        "losses": clean_count(losses),
        "win_rate_percent": "" if win_rate is None else win_rate,
        "pnl": "" if pnl is None else pnl,
        "summary": summary[:5000],
        "report_tail": report[-12000:],
        "raw_file": str(raw_file),
        "error": payload.get("error", ""),
    }


def scalar_trade_record(item: Dict[str, Any], date_text: str, path: str) -> Optional[Dict[str, Any]]:
    normalized_keys = {str(key).lower() for key in item.keys()}
    score = len(normalized_keys & TRADE_HINT_KEYS)
    if score < 3:
        return None

    record: Dict[str, Any] = {"backtest_date": date_text, "source_path": path}
    for key, value in item.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            record[str(key)] = value
    return record


def find_trade_records(value: Any, date_text: str, path: str = "result") -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if isinstance(value, dict):
        candidate = scalar_trade_record(value, date_text, path)
        if candidate:
            records.append(candidate)
        for key, item in value.items():
            records.extend(find_trade_records(item, date_text, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            records.extend(find_trade_records(item, date_text, f"{path}[{index}]"))
    return records


def write_csv(path: Path, rows: List[Dict[str, Any]], preferred: Optional[List[str]] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if preferred is None:
        keys = set()
        for row in rows:
            keys.update(row.keys())
        columns = sorted(keys)
    else:
        columns = preferred
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def load_existing_summary(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        with path.open("r", newline="", encoding="utf-8") as handle:
            return {str(row.get("date")): row for row in csv.DictReader(handle) if row.get("date")}
    except Exception:
        return {}


def parse_worker_payload(stdout: str) -> Dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        if line.startswith(WORKER_SENTINEL):
            return json.loads(line[len(WORKER_SENTINEL) :])
    raise RuntimeError("Worker JSON sentinel not found")


def run_batch(args: argparse.Namespace) -> int:
    start = parse_date(args.date_from)
    end = parse_date(args.date_to)
    if end < start:
        raise SystemExit("date-to cannot be earlier than date-from")

    output_dir = Path(args.output_dir)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "backtest_range_summary.csv"
    trades_path = output_dir / "backtest_trade_records.csv"
    metadata_path = output_dir / "metadata.json"

    dates = discover_cached_dates(start, end)
    date_source = "cached_spot_files"
    if not dates:
        dates = fallback_weekdays(start, end)
        date_source = "weekday_fallback"

    existing = load_existing_summary(summary_path)
    summary_rows: Dict[str, Dict[str, Any]] = dict(existing)
    trade_rows: List[Dict[str, Any]] = []

    print("=== OKAI BACKTEST RANGE EXPORT ===")
    print("date_from =", args.date_from)
    print("date_to =", args.date_to)
    print("mode =", args.mode)
    print("date_source =", date_source)
    print("dates_found =", len(dates))
    print("resume =", args.resume)
    print("orders = HARD BLOCKED")
    print()

    completed = 0
    errors = 0
    timed_out = 0
    script_path = Path(__file__).resolve()

    for index, date_text in enumerate(dates, start=1):
        raw_file = raw_dir / f"{date_text}.json"
        old = summary_rows.get(date_text)
        if args.resume and old and old.get("status") == "ok" and raw_file.exists():
            print(f"[{index}/{len(dates)}] {date_text} | SKIP completed")
            completed += 1
            try:
                payload = json.loads(raw_file.read_text(encoding="utf-8"))
                trade_rows.extend(find_trade_records(payload.get("result"), date_text))
            except Exception:
                pass
            continue

        command = [
            sys.executable,
            str(script_path),
            "--worker",
            "--date",
            date_text,
            "--mode",
            args.mode,
        ]
        env = os.environ.copy()
        env["OPENBLAS_NUM_THREADS"] = "1"
        env["OMP_NUM_THREADS"] = "1"
        env["PYTHONUNBUFFERED"] = "1"

        started = time.time()
        try:
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=args.timeout,
                env=env,
            )
            try:
                payload = parse_worker_payload(process.stdout)
            except Exception as exc:
                payload = {
                    "status": "error",
                    "date": date_text,
                    "mode": args.mode,
                    "duration_seconds": round(time.time() - started, 3),
                    "result_type": "",
                    "result": None,
                    "captured_stdout": process.stdout[-MAX_CAPTURE_CHARS:],
                    "captured_stderr": process.stderr[-MAX_CAPTURE_CHARS:],
                    "error": f"worker_parse_failed:{exc!r}",
                    "orders": "BLOCKED",
                }
        except subprocess.TimeoutExpired as exc:
            timed_out += 1
            payload = {
                "status": "timeout",
                "date": date_text,
                "mode": args.mode,
                "duration_seconds": round(time.time() - started, 3),
                "result_type": "",
                "result": None,
                "captured_stdout": (exc.stdout or "")[-MAX_CAPTURE_CHARS:] if isinstance(exc.stdout, str) else "",
                "captured_stderr": (exc.stderr or "")[-MAX_CAPTURE_CHARS:] if isinstance(exc.stderr, str) else "",
                "error": f"timeout_after_{args.timeout}_seconds",
                "orders": "BLOCKED",
            }

        raw_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        row = extract_summary_row(payload, raw_file)
        summary_rows[date_text] = row
        trade_rows.extend(find_trade_records(payload.get("result"), date_text))

        ordered_rows = [summary_rows[key] for key in sorted(summary_rows)]
        write_csv(summary_path, ordered_rows, SUMMARY_FIELDS)

        status = str(payload.get("status"))
        if status == "ok":
            completed += 1
        else:
            errors += 1
        print(
            f"[{index}/{len(dates)}] {date_text}",
            "|", status.upper(),
            "| trades =", row.get("closed_trades") or "?",
            "| pnl =", row.get("pnl") or "?",
            "| sec =", row.get("duration_seconds") or "?",
        )

    # Rebuild trade records from every successful raw file so resume remains complete.
    all_trade_rows: List[Dict[str, Any]] = []
    for raw_file in sorted(raw_dir.glob("*.json")):
        try:
            payload = json.loads(raw_file.read_text(encoding="utf-8"))
            all_trade_rows.extend(find_trade_records(payload.get("result"), str(payload.get("date") or raw_file.stem)))
        except Exception:
            continue
    write_csv(trades_path, all_trade_rows)

    final_rows = [summary_rows[key] for key in sorted(summary_rows)]
    ok_rows = [row for row in final_rows if row.get("status") == "ok"]
    pnl_values = []
    trade_counts = []
    for row in ok_rows:
        try:
            pnl_values.append(float(row["pnl"]))
        except Exception:
            pass
        try:
            trade_counts.append(int(float(row["closed_trades"])))
        except Exception:
            pass

    metadata = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "date_from": args.date_from,
        "date_to": args.date_to,
        "mode": args.mode,
        "date_source": date_source,
        "dates_requested": len(dates),
        "successful_dates": len(ok_rows),
        "failed_or_timeout_dates": len(final_rows) - len(ok_rows),
        "parsed_trade_records": len(all_trade_rows),
        "parsed_total_closed_trades": sum(trade_counts) if trade_counts else None,
        "parsed_total_pnl": round(sum(pnl_values), 2) if pnl_values else None,
        "summary_csv": str(summary_path),
        "trade_records_csv": str(trades_path),
        "raw_dir": str(raw_dir),
        "orders": "HARD BLOCKED",
        "model_training": "NOT RUN",
        "paper": "BLOCKED",
        "live": "BLOCKED",
        "note": "Trade records CSV is automatic best-effort extraction; raw per-date JSON remains the source of truth.",
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print()
    print("=== RANGE EXPORT COMPLETE ===")
    print("successful_dates =", len(ok_rows))
    print("failed_or_timeout_dates =", len(final_rows) - len(ok_rows))
    print("parsed_trade_records =", len(all_trade_rows))
    print("summary_csv =", summary_path)
    print("trade_records_csv =", trades_path)
    print("raw_results =", raw_dir)
    print("metadata =", metadata_path)
    print("model_training = NOT RUN")
    print("paper/live = BLOCKED")
    print("server/orders = UNCHANGED / BLOCKED")
    return 0 if errors == 0 and timed_out == 0 else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date-from", default="2026-01-01")
    parser.add_argument("--date-to", default="2026-06-30")
    parser.add_argument("--mode", default="REALISTIC")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--date", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.worker:
        if not args.date:
            raise SystemExit("worker requires --date")
        return worker(args.date, args.mode)
    return run_batch(args)


if __name__ == "__main__":
    raise SystemExit(main())
