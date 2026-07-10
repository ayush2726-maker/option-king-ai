"""Diagnose first-hit NIFTY labels before training another model.

For each eligible 1-minute candle, the script checks the next N minutes and
records which symmetric ATR barrier is touched first: upper (CE), lower (PE),
neither (NO_TRADE), or both inside the same candle (AMBIGUOUS). It does not
train a model, import app.py, or execute orders.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from train_nifty_shadow_model import DEFAULT_SPOT_DIRS, discover_spot_files, load_candles


OUTPUT_PATH = Path("data/ml_models/nifty_first_hit_label_diagnostic.json")


def prepare_candles(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy().sort_values("timestamp").reset_index(drop=True)
    group = df.groupby("date", sort=False)
    previous_close = group["close"].shift(1)
    df["true_range"] = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr14"] = group["true_range"].transform(
        lambda series: series.rolling(14, min_periods=14).mean()
    )
    df["minute_from_open"] = (df["hour"] * 60 + df["minute"]) - 555
    return df


def date_splits(df: pd.DataFrame) -> Dict[str, List[str]]:
    dates = sorted(df["date"].unique().tolist())
    train_end = int(len(dates) * 0.70)
    validation_end = min(int(len(dates) * 0.85), len(dates) - 1)
    return {
        "train": dates[:train_end],
        "validation": dates[train_end:validation_end],
        "test": dates[validation_end:],
    }


def evaluate_multiplier(
    df: pd.DataFrame,
    horizon: int,
    multiplier: float,
) -> pd.DataFrame:
    records = []

    for date_value, day in df.groupby("date", sort=False):
        day = day.sort_values("timestamp").reset_index(drop=True)
        highs = day["high"].to_numpy(dtype=np.float64)
        lows = day["low"].to_numpy(dtype=np.float64)
        closes = day["close"].to_numpy(dtype=np.float64)
        atr = day["atr14"].to_numpy(dtype=np.float64)
        minutes = day["minute_from_open"].to_numpy(dtype=np.int64)
        timestamps = day["timestamp"].astype(str).to_numpy()

        for index in range(len(day)):
            if not np.isfinite(atr[index]) or atr[index] <= 0:
                continue
            if minutes[index] < 10 or minutes[index] > 375 - horizon:
                continue
            if index + horizon >= len(day):
                continue

            upper = closes[index] + multiplier * atr[index]
            lower = closes[index] - multiplier * atr[index]
            label = "NO_TRADE"
            bars_to_hit = None

            for offset in range(1, horizon + 1):
                hit_up = highs[index + offset] >= upper
                hit_down = lows[index + offset] <= lower

                if hit_up and hit_down:
                    label = "AMBIGUOUS"
                    bars_to_hit = offset
                    break
                if hit_up:
                    label = "CE"
                    bars_to_hit = offset
                    break
                if hit_down:
                    label = "PE"
                    bars_to_hit = offset
                    break

            records.append(
                {
                    "timestamp": timestamps[index],
                    "date": date_value,
                    "label": label,
                    "bars_to_hit": bars_to_hit,
                    "atr": float(atr[index]),
                    "barrier_points": float(multiplier * atr[index]),
                }
            )

    return pd.DataFrame.from_records(records)


def summarize(frame: pd.DataFrame) -> Dict[str, object]:
    total = len(frame)
    counts = {
        name: int((frame["label"] == name).sum())
        for name in ("NO_TRADE", "CE", "PE", "AMBIGUOUS")
    }
    rates = {
        name: (count / total if total else 0.0)
        for name, count in counts.items()
    }

    hit_frame = frame[frame["label"].isin(["CE", "PE"])]
    return {
        "rows": total,
        "counts": counts,
        "rates": rates,
        "directional_rate": rates["CE"] + rates["PE"],
        "ce_pe_balance": (
            min(counts["CE"], counts["PE"])
            / max(counts["CE"], counts["PE"], 1)
        ),
        "median_bars_to_directional_hit": (
            float(hit_frame["bars_to_hit"].median()) if not hit_frame.empty else None
        ),
        "mean_barrier_points": (
            float(frame["barrier_points"].mean()) if total else None
        ),
    }


def print_summary(title: str, summary: Dict[str, object]) -> None:
    print(title)
    print("rows =", summary["rows"])
    print("counts =", summary["counts"])
    print("rates =", {k: round(v, 4) for k, v in summary["rates"].items()})
    print("directional_rate =", round(float(summary["directional_rate"]), 4))
    print("ce_pe_balance =", round(float(summary["ce_pe_balance"]), 4))
    print("median_bars_to_directional_hit =", summary["median_bars_to_directional_hit"])
    print("mean_barrier_points =", round(float(summary["mean_barrier_points"] or 0.0), 2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon", type=int, default=15)
    parser.add_argument(
        "--multipliers",
        type=float,
        nargs="+",
        default=[0.50, 0.75, 1.00, 1.25],
    )
    args = parser.parse_args()

    files = discover_spot_files(DEFAULT_SPOT_DIRS)
    candles = prepare_candles(load_candles(files))
    splits = date_splits(candles)

    print("=== NIFTY FIRST-HIT LABEL DIAGNOSTIC ===")
    print("source_files =", len(files))
    print("raw_candles =", len(candles))
    print("horizon_minutes =", args.horizon)
    print(
        "date_range =",
        candles["date"].min(),
        "to",
        candles["date"].max(),
    )

    result: Dict[str, object] = {
        "source_files": len(files),
        "raw_candles": len(candles),
        "horizon_minutes": args.horizon,
        "date_splits": splits,
        "multipliers": {},
    }

    for multiplier in args.multipliers:
        labelled = evaluate_multiplier(candles, args.horizon, multiplier)
        multiplier_result = {"all": summarize(labelled)}
        print(f"\n=== ATR MULTIPLIER {multiplier:.2f} ===")
        print_summary("ALL", multiplier_result["all"])

        for split_name, split_dates in splits.items():
            split_frame = labelled[labelled["date"].isin(split_dates)]
            split_summary = summarize(split_frame)
            multiplier_result[split_name] = split_summary
            print_summary(split_name.upper(), split_summary)

        result["multipliers"][str(multiplier)] = multiplier_result

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("\noutput =", OUTPUT_PATH)
    print("training = NOT RUN")
    print("paper = BLOCKED")
    print("live = BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
