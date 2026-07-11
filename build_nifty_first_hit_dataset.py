"""Build a leak-safe NIFTY first-hit training dataset.

Uses the selected 5-minute / 2.5 ATR first-hit label setting, merges it with
technical features that only use information available at the current candle,
drops ambiguous rows, applies chronological train/validation/test splits, and
exports CSV plus metadata. It never imports app.py or executes orders.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import pandas as pd

from diagnose_nifty_first_hit_labels import evaluate_multiplier, prepare_candles
from train_nifty_shadow_model import DEFAULT_SPOT_DIRS, discover_spot_files, load_candles
from train_nifty_two_stage_shadow import ALL_FEATURES, build_dataset


OUTPUT_DIR = Path("data/ml_training")
CLASS_TO_ID = {"NO_TRADE": 0, "CE": 1, "PE": 2}


def split_dates(dates: List[str]) -> Dict[str, List[str]]:
    dates = sorted(dates)
    train_end = int(len(dates) * 0.70)
    validation_end = min(int(len(dates) * 0.85), len(dates) - 1)
    return {
        "train": dates[:train_end],
        "validation": dates[train_end:validation_end],
        "test": dates[validation_end:],
    }


def class_distribution(frame: pd.DataFrame) -> Dict[str, int]:
    counts = frame["target_label"].value_counts().to_dict()
    return {name: int(counts.get(name, 0)) for name in ("NO_TRADE", "CE", "PE")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--atr-multiplier", type=float, default=2.5)
    args = parser.parse_args()

    files = discover_spot_files(DEFAULT_SPOT_DIRS)
    raw = load_candles(files)

    feature_frame = build_dataset(raw, args.horizon).copy()
    feature_frame["timestamp"] = pd.to_datetime(feature_frame["timestamp"], errors="coerce")

    labelled = evaluate_multiplier(
        prepare_candles(raw),
        args.horizon,
        args.atr_multiplier,
    ).copy()
    labelled["timestamp"] = pd.to_datetime(labelled["timestamp"], errors="coerce")
    labelled = labelled.rename(columns={"label": "target_label"})

    dataset = feature_frame.merge(
        labelled[["timestamp", "date", "target_label", "bars_to_hit", "barrier_points"]],
        on=["timestamp", "date"],
        how="inner",
        validate="one_to_one",
    )

    ambiguous_rows = int((dataset["target_label"] == "AMBIGUOUS").sum())
    dataset = dataset[dataset["target_label"].isin(CLASS_TO_ID)].copy()
    dataset["target_id"] = dataset["target_label"].map(CLASS_TO_ID).astype(int)

    selected_columns = [
        "timestamp",
        "date",
        "open",
        "high",
        "low",
        "close",
        *ALL_FEATURES,
        "target_id",
        "target_label",
        "bars_to_hit",
        "barrier_points",
    ]
    dataset = dataset[selected_columns].sort_values("timestamp").reset_index(drop=True)

    dates = sorted(dataset["date"].unique().tolist())
    splits = split_dates(dates)
    dataset["split"] = ""
    for split_name, split_date_values in splits.items():
        dataset.loc[dataset["date"].isin(split_date_values), "split"] = split_name

    if (dataset["split"] == "").any():
        raise RuntimeError("Some rows were not assigned to a chronological split")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / "nifty_first_hit_5m_2p5atr_dataset.csv"
    metadata_path = OUTPUT_DIR / "nifty_first_hit_5m_2p5atr_metadata.json"
    dataset.to_csv(csv_path, index=False)

    metadata = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "symbol": "NIFTY",
        "timeframe": "ONE_MINUTE",
        "horizon_minutes": args.horizon,
        "atr_multiplier": args.atr_multiplier,
        "label_method": "first symmetric ATR barrier touched within horizon",
        "ambiguous_rows_dropped": ambiguous_rows,
        "source_file_count": len(files),
        "raw_candles": len(raw),
        "dataset_rows": len(dataset),
        "feature_columns": ALL_FEATURES,
        "target_mapping": CLASS_TO_ID,
        "date_splits": splits,
        "row_splits": {
            name: int((dataset["split"] == name).sum())
            for name in ("train", "validation", "test")
        },
        "class_distribution": {
            name: class_distribution(dataset[dataset["split"] == name])
            for name in ("train", "validation", "test")
        },
        "approved_for_shadow": False,
        "approved_for_paper": False,
        "approved_for_live": False,
        "order_execution": False,
        "notes": [
            "Dataset only; no model has been trained or approved.",
            "Features exclude future high, future low, and all label-derived columns.",
            "Use chronological validation and walk-forward testing for tree models.",
        ],
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print("=== FIRST-HIT DATASET READY ===")
    print("source_files =", len(files))
    print("raw_candles =", len(raw))
    print("dataset_rows =", len(dataset))
    print("ambiguous_rows_dropped =", ambiguous_rows)
    print("horizon_minutes =", args.horizon)
    print("atr_multiplier =", args.atr_multiplier)
    for name in ("train", "validation", "test"):
        subset = dataset[dataset["split"] == name]
        print(
            f"{name}_dates =",
            len(splits[name]),
            splits[name][0],
            "to",
            splits[name][-1],
        )
        print(f"{name}_rows =", len(subset))
        print(f"{name}_distribution =", class_distribution(subset))
    print("csv =", csv_path)
    print("metadata =", metadata_path)
    print("training = NOT RUN")
    print("paper = BLOCKED")
    print("live = BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
