"""Build a leakage-safe trade-quality gate dataset from parsed backtest trades.

The resulting dataset is for research only. It predicts whether a proposed
trade is likely to finish profitable using information known before entry.
Post-entry fields such as exit price, exit reason, duration and realized P&L
are excluded from features.

Safety: does not import app.py and cannot place/modify/cancel orders.
"""

from __future__ import annotations

import csv
import json
import math
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

SOURCE = Path("data/ml_models/jan_jun_trade_sequence/parsed_trades.csv")
POLICIES = Path("data/ml_models/jan_jun_trade_sequence/policy_comparison.csv")
OUT_DIR = Path("data/ml_training/trade_quality_gate_v1")
DATASET = OUT_DIR / "trade_quality_gate_v1_dataset.csv"
METADATA = OUT_DIR / "trade_quality_gate_v1_metadata.json"
PACKAGE = Path("trade_quality_gate_v1_training_package.zip")

FEATURES = [
    "trade_index",
    "is_first_trade",
    "side_ce",
    "side_pe",
    "entry_minute_from_open",
    "entry_time_sin",
    "entry_time_cos",
    "entry_price",
    "qty",
    "entry_notional",
    "day_of_week",
    "month",
    "prior_trades",
    "prior_wins",
    "prior_losses",
    "prior_loss_streak",
    "prior_win_streak",
    "prior_cumulative_net",
    "previous_trade_net",
    "previous_trade_was_win",
    "previous_trade_was_loss",
    "same_side_as_previous",
    "minutes_since_previous_exit",
]

FORBIDDEN_FEATURE_WORDS = (
    "exit",
    "reason",
    "duration",
    "gross",
    "charges",
    "net",
    "result",
    "label",
    "target",
    "momentum",
    "raw",
)


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return default
    return result if math.isfinite(result) else default


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def parse_dt(trade_date: str, time_text: str) -> datetime:
    return datetime.fromisoformat(f"{trade_date} {time_text}")


def minute_from_open(time_text: str) -> int:
    hours, minutes, _ = [int(part) for part in time_text.split(":")]
    return max(0, hours * 60 + minutes - (9 * 60 + 15))


def split_dates(dates: List[str]) -> Dict[str, List[str]]:
    if len(dates) < 10:
        raise RuntimeError("Too few active dates for chronological split")

    train_end = max(1, int(len(dates) * 0.60))
    validation_end = max(train_end + 1, int(len(dates) * 0.80))
    validation_end = min(validation_end, len(dates) - 1)

    return {
        "TRAIN": dates[:train_end],
        "VALIDATION": dates[train_end:validation_end],
        "TEST": dates[validation_end:],
    }


def load_policy_baselines() -> List[Dict[str, Any]]:
    if not POLICIES.exists():
        return []
    with POLICIES.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(
            "Missing parsed trades. Run analyze_trade_sequence_policies.py first."
        )

    with SOURCE.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    if not rows:
        raise SystemExit("Parsed trade file is empty")

    rows.sort(key=lambda row: (row["date"], integer(row["trade_index"])))
    active_dates = sorted({row["date"] for row in rows})
    splits = split_dates(active_dates)
    split_lookup = {
        trade_date: split
        for split, split_dates_list in splits.items()
        for trade_date in split_dates_list
    }

    dataset_rows: List[Dict[str, Any]] = []
    by_day: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_day[row["date"]].append(row)

    for trade_date in active_dates:
        prior_trades = 0
        prior_wins = 0
        prior_losses = 0
        prior_loss_streak = 0
        prior_win_streak = 0
        prior_cumulative_net = 0.0
        previous_trade_net = 0.0
        previous_side = ""
        previous_exit_dt: Optional[datetime] = None

        for source in by_day[trade_date]:
            trade_index = integer(source["trade_index"])
            side = str(source.get("side") or "").upper()
            entry_time = str(source["entry_time"])
            entry_dt = parse_dt(trade_date, entry_time)
            entry_minute = minute_from_open(entry_time)
            angle = 2.0 * math.pi * entry_minute / 375.0

            entry_price = number(source.get("entry_price"))
            qty = integer(source.get("qty"))
            realized_net = number(source.get("net"))
            label = 1 if realized_net > 0 else 0

            minutes_since_previous_exit = 999.0
            if previous_exit_dt is not None:
                minutes_since_previous_exit = max(
                    0.0,
                    (entry_dt - previous_exit_dt).total_seconds() / 60.0,
                )

            record: Dict[str, Any] = {
                "date": trade_date,
                "split": split_lookup[trade_date],
                "label_win": label,
                "target_net": round(realized_net, 2),
                "trade_index": trade_index,
                "is_first_trade": 1 if trade_index == 1 else 0,
                "side_ce": 1 if side == "CE" else 0,
                "side_pe": 1 if side == "PE" else 0,
                "entry_minute_from_open": entry_minute,
                "entry_time_sin": round(math.sin(angle), 8),
                "entry_time_cos": round(math.cos(angle), 8),
                "entry_price": round(entry_price, 4),
                "qty": qty,
                "entry_notional": round(entry_price * qty, 2),
                "day_of_week": entry_dt.weekday(),
                "month": entry_dt.month,
                "prior_trades": prior_trades,
                "prior_wins": prior_wins,
                "prior_losses": prior_losses,
                "prior_loss_streak": prior_loss_streak,
                "prior_win_streak": prior_win_streak,
                "prior_cumulative_net": round(prior_cumulative_net, 2),
                "previous_trade_net": round(previous_trade_net, 2),
                "previous_trade_was_win": 1 if previous_trade_net > 0 else 0,
                "previous_trade_was_loss": 1 if previous_trade_net < 0 else 0,
                "same_side_as_previous": 1 if previous_side == side and previous_side else 0,
                "minutes_since_previous_exit": round(minutes_since_previous_exit, 2),
            }
            dataset_rows.append(record)

            prior_trades += 1
            if realized_net > 0:
                prior_wins += 1
                prior_win_streak += 1
                prior_loss_streak = 0
            elif realized_net < 0:
                prior_losses += 1
                prior_loss_streak += 1
                prior_win_streak = 0

            prior_cumulative_net += realized_net
            previous_trade_net = realized_net
            previous_side = side
            previous_exit_dt = parse_dt(trade_date, str(source["exit_time"]))

    forbidden = [
        feature
        for feature in FEATURES
        if any(word in feature.lower() for word in FORBIDDEN_FEATURE_WORDS)
    ]
    if forbidden:
        raise RuntimeError(f"Forbidden/leaky features detected: {forbidden}")

    if len(dataset_rows) != len(rows):
        raise RuntimeError(
            f"Row mismatch: source={len(rows)} dataset={len(dataset_rows)}"
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = ["date", "split", "label_win", "target_net", *FEATURES]
    with DATASET.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(dataset_rows)

    split_summary: Dict[str, Dict[str, Any]] = {}
    for split in ("TRAIN", "VALIDATION", "TEST"):
        selected = [row for row in dataset_rows if row["split"] == split]
        wins = sum(integer(row["label_win"]) for row in selected)
        split_dates_list = splits[split]
        split_summary[split] = {
            "rows": len(selected),
            "dates": len(split_dates_list),
            "date_from": split_dates_list[0],
            "date_to": split_dates_list[-1],
            "wins": wins,
            "losses": len(selected) - wins,
            "win_rate": round((wins / len(selected)) if selected else 0.0, 6),
        }

    metadata = {
        "name": "trade-quality-gate-v1",
        "purpose": "Research-only pre-entry allow/block meta-model",
        "source": str(SOURCE),
        "rows": len(dataset_rows),
        "active_dates": len(active_dates),
        "feature_columns": FEATURES,
        "label_column": "label_win",
        "regression_audit_target": "target_net",
        "strict_feature_rule": "Only feature_columns may be used for training",
        "excluded_post_entry_fields": [
            "exit_time",
            "exit_price",
            "duration_seconds",
            "gross",
            "charges",
            "net",
            "result",
            "reason",
            "reason_text",
            "momentum",
            "raw",
        ],
        "split_summary": split_summary,
        "policy_baselines": load_policy_baselines(),
        "limitations": [
            "Only 175 synthetic-estimate backtest trades",
            "Not actual option LTP execution data",
            "Jan-Jun period has already been inspected and is not fully untouched",
            "Model must use chronological walk-forward validation",
            "No deployment unless it beats simple policy baselines out of sample",
        ],
        "training": "NOT RUN",
        "shadow": "BLOCKED",
        "paper": "BLOCKED",
        "live": "BLOCKED",
        "orders": "DISABLED",
    }
    METADATA.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with zipfile.ZipFile(PACKAGE, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(DATASET, DATASET.name)
        archive.write(METADATA, METADATA.name)
        archive.write(SOURCE, SOURCE.name)
        if POLICIES.exists():
            archive.write(POLICIES, POLICIES.name)

    print("=== TRADE QUALITY GATE DATASET READY ===")
    print("source_trades =", len(rows))
    print("dataset_rows =", len(dataset_rows))
    print("active_dates =", len(active_dates))
    print("features =", len(FEATURES))
    print("leakage_check = PASS")
    for split in ("TRAIN", "VALIDATION", "TEST"):
        item = split_summary[split]
        print(
            split,
            "| rows =", item["rows"],
            "| dates =", item["dates"],
            "| range =", item["date_from"], "to", item["date_to"],
            "| W/L =", f"{item['wins']}/{item['losses']}",
            "| win_rate =", f"{item['win_rate'] * 100:.2f}%",
        )
    print("dataset =", DATASET)
    print("metadata =", METADATA)
    print("package =", PACKAGE)
    print("training = NOT RUN")
    print("shadow = BLOCKED")
    print("paper = BLOCKED")
    print("live = BLOCKED")
    print("server/orders = UNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
