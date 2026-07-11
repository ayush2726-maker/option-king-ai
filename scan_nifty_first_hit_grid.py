"""Compact grid scan for NIFTY first-hit barrier labels.

Scans multiple horizons and ATR multipliers, reports train/validation/test label
rates, and flags only stable candidate settings. No model training or orders.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from diagnose_nifty_first_hit_labels import (
    date_splits,
    evaluate_multiplier,
    prepare_candles,
    summarize,
)
from train_nifty_shadow_model import DEFAULT_SPOT_DIRS, discover_spot_files, load_candles


CSV_PATH = Path("data/ml_models/nifty_first_hit_grid.csv")
JSON_PATH = Path("data/ml_models/nifty_first_hit_grid.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizons", type=int, nargs="+", default=[5, 10, 15])
    parser.add_argument(
        "--multipliers",
        type=float,
        nargs="+",
        default=[1.5, 2.0, 2.5, 3.0, 4.0, 5.0],
    )
    args = parser.parse_args()

    files = discover_spot_files(DEFAULT_SPOT_DIRS)
    candles = prepare_candles(load_candles(files))
    splits = date_splits(candles)
    rows = []

    print("=== NIFTY FIRST-HIT GRID ===")
    print("source_files =", len(files))
    print("raw_candles =", len(candles))
    print()
    print(
        "H  ATR | TEST_NO  TEST_DIR  TEST_AMB  BALANCE | "
        "TRAIN_DIR VAL_DIR TEST_DIR | STATUS"
    )

    for horizon in args.horizons:
        for multiplier in args.multipliers:
            labelled = evaluate_multiplier(candles, horizon, multiplier)
            summaries = {}
            for name, dates in splits.items():
                summaries[name] = summarize(labelled[labelled["date"].isin(dates)])

            train_dir = float(summaries["train"]["directional_rate"])
            val_dir = float(summaries["validation"]["directional_rate"])
            test_dir = float(summaries["test"]["directional_rate"])
            test_no = float(summaries["test"]["rates"]["NO_TRADE"])
            test_amb = float(summaries["test"]["rates"]["AMBIGUOUS"])
            balance = float(summaries["test"]["ce_pe_balance"])
            drift = max(train_dir, val_dir, test_dir) - min(train_dir, val_dir, test_dir)

            candidate = (
                0.10 <= test_dir <= 0.35
                and 0.60 <= test_no <= 0.90
                and test_amb <= 0.01
                and balance >= 0.75
                and drift <= 0.12
            )
            status = "CANDIDATE" if candidate else "NO"

            row = {
                "horizon": horizon,
                "atr_multiplier": multiplier,
                "train_directional_rate": train_dir,
                "validation_directional_rate": val_dir,
                "test_directional_rate": test_dir,
                "test_no_trade_rate": test_no,
                "test_ambiguous_rate": test_amb,
                "test_ce_pe_balance": balance,
                "directional_rate_drift": drift,
                "test_mean_barrier_points": summaries["test"]["mean_barrier_points"],
                "test_median_bars_to_hit": summaries["test"]["median_bars_to_directional_hit"],
                "status": status,
            }
            rows.append(row)

            print(
                f"{horizon:>2} {multiplier:>4.1f} | "
                f"{test_no:>7.3f} {test_dir:>8.3f} {test_amb:>8.3f} {balance:>8.3f} | "
                f"{train_dir:>9.3f} {val_dir:>7.3f} {test_dir:>8.3f} | {status}"
            )

    frame = pd.DataFrame(rows)
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(CSV_PATH, index=False)
    JSON_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    candidates = frame[frame["status"] == "CANDIDATE"].copy()
    print()
    print("candidate_count =", len(candidates))
    if not candidates.empty:
        candidates = candidates.sort_values(
            ["directional_rate_drift", "test_ce_pe_balance"],
            ascending=[True, False],
        )
        print("best_candidates =")
        print(
            candidates[
                [
                    "horizon",
                    "atr_multiplier",
                    "test_no_trade_rate",
                    "test_directional_rate",
                    "test_ce_pe_balance",
                    "directional_rate_drift",
                    "test_mean_barrier_points",
                ]
            ].head(10).to_string(index=False)
        )
    else:
        print("No stable label setting found in this grid.")

    print("csv =", CSV_PATH)
    print("json =", JSON_PATH)
    print("training = NOT RUN")
    print("paper = BLOCKED")
    print("live = BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
