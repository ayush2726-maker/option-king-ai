"""Train a prototype NIFTY direction model without scikit-learn.

The trainer uses only pandas and NumPy so it can run on Android/Termux.
It reads cached NIFTY 1-minute spot candles, builds non-leaking technical
features, splits by trading date, trains a weighted multiclass softmax model,
and saves the model for shadow evaluation only.

This script does not import app.py and cannot place, modify, or exit trades.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np
import pandas as pd


MODEL_VERSION = "nifty-softmax-shadow-0.1.0"
CLASS_NAMES = np.array(["NO_TRADE", "CE", "PE"], dtype=object)
DEFAULT_SPOT_DIRS = (
    Path("data/angel_cache/spot_candles"),
    Path("users/owner/data/angel_cache/spot_candles"),
)
DEFAULT_OUTPUT_DIR = Path("data/ml_models")


FEATURE_COLUMNS = [
    "return_1",
    "return_3",
    "return_5",
    "return_10",
    "ema_gap_9_21",
    "close_vs_ema9",
    "close_vs_ema21",
    "rsi14_scaled",
    "atr14_percent",
    "range_percent",
    "body_percent",
    "rolling_vol_5",
    "rolling_vol_15",
    "distance_day_open",
    "position_in_15_range",
    "minute_from_open_scaled",
]


@dataclass
class SplitData:
    name: str
    frame: pd.DataFrame
    x: np.ndarray
    y: np.ndarray


def _load_json_rows(path: Path) -> List[Sequence[object]]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return []

    if isinstance(obj, list):
        rows = obj
    elif isinstance(obj, dict):
        rows = obj.get("data") or obj.get("candles") or obj.get("rows") or []
    else:
        rows = []

    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, (list, tuple)) and len(row) >= 5]


def discover_spot_files(roots: Iterable[Path]) -> List[Path]:
    """Return one preferred file per trading date.

    The main cache is preferred over the users/owner mirror. Duplicate dates
    are not counted twice.
    """
    chosen: Dict[str, Path] = {}
    for priority, root in enumerate(roots):
        if not root.exists():
            continue
        for path in sorted(root.glob("NSE_99926000_ONE_MINUTE_*.json")):
            date_key = path.stem.rsplit("_", 1)[-1]
            if len(date_key) != 8 or not date_key.isdigit():
                continue
            if date_key not in chosen or priority == 0:
                chosen[date_key] = path
    return [chosen[key] for key in sorted(chosen)]


def load_candles(files: Sequence[Path]) -> pd.DataFrame:
    records: List[Tuple[object, object, object, object, object, object, str]] = []
    for path in files:
        for row in _load_json_rows(path):
            volume = row[5] if len(row) > 5 else 0
            records.append((row[0], row[1], row[2], row[3], row[4], volume, str(path)))

    if not records:
        raise RuntimeError("No readable NIFTY spot candle rows found")

    frame = pd.DataFrame(
        records,
        columns=["timestamp", "open", "high", "low", "close", "volume", "source_file"],
    )
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    frame["date"] = frame["timestamp"].dt.date.astype(str)
    frame["hour"] = frame["timestamp"].dt.hour
    frame["minute"] = frame["timestamp"].dt.minute
    frame = frame.reset_index(drop=True)
    return frame


def _group_transform(frame: pd.DataFrame, column: str, func) -> pd.Series:
    return frame.groupby("date", sort=False)[column].transform(func)


def build_dataset(frame: pd.DataFrame, horizon_minutes: int) -> pd.DataFrame:
    df = frame.copy()
    group = df.groupby("date", sort=False)

    for periods in (1, 3, 5, 10):
        df[f"return_{periods}"] = group["close"].pct_change(periods, fill_method=None)

    df["ema9"] = _group_transform(
        df,
        "close",
        lambda series: series.ewm(span=9, adjust=False).mean(),
    )
    df["ema21"] = _group_transform(
        df,
        "close",
        lambda series: series.ewm(span=21, adjust=False).mean(),
    )
    df["ema_gap_9_21"] = (df["ema9"] - df["ema21"]) / df["close"]
    df["close_vs_ema9"] = (df["close"] - df["ema9"]) / df["close"]
    df["close_vs_ema21"] = (df["close"] - df["ema21"]) / df["close"]

    previous_close = group["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["true_range"] = true_range
    df["atr14"] = _group_transform(
        df,
        "true_range",
        lambda series: series.rolling(14, min_periods=14).mean(),
    )
    df["atr14_percent"] = df["atr14"] / df["close"]

    delta = group["close"].diff()
    df["gain"] = delta.clip(lower=0)
    df["loss"] = (-delta).clip(lower=0)
    avg_gain = _group_transform(
        df,
        "gain",
        lambda series: series.rolling(14, min_periods=14).mean(),
    )
    avg_loss = _group_transform(
        df,
        "loss",
        lambda series: series.rolling(14, min_periods=14).mean(),
    )
    relative_strength = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + relative_strength))
    rsi = rsi.where(avg_loss > 0, 100.0)
    rsi = rsi.where(avg_gain > 0, 0.0)
    df["rsi14_scaled"] = (rsi - 50.0) / 50.0

    df["range_percent"] = (df["high"] - df["low"]) / df["close"]
    df["body_percent"] = (df["close"] - df["open"]) / df["open"]
    df["rolling_vol_5"] = _group_transform(
        df,
        "return_1",
        lambda series: series.rolling(5, min_periods=5).std(ddof=0),
    )
    df["rolling_vol_15"] = _group_transform(
        df,
        "return_1",
        lambda series: series.rolling(15, min_periods=15).std(ddof=0),
    )

    day_open = group["open"].transform("first")
    df["distance_day_open"] = (df["close"] - day_open) / day_open

    rolling_high = _group_transform(
        df,
        "high",
        lambda series: series.rolling(15, min_periods=15).max(),
    )
    rolling_low = _group_transform(
        df,
        "low",
        lambda series: series.rolling(15, min_periods=15).min(),
    )
    range_15 = (rolling_high - rolling_low).replace(0, np.nan)
    df["position_in_15_range"] = ((df["close"] - rolling_low) / range_15) * 2.0 - 1.0

    minute_from_open = (df["hour"] * 60 + df["minute"]) - (9 * 60 + 15)
    df["minute_from_open"] = minute_from_open
    df["minute_from_open_scaled"] = (minute_from_open - 187.5) / 187.5

    df["future_close"] = group["close"].shift(-horizon_minutes)
    df["future_return"] = (df["future_close"] / df["close"]) - 1.0

    volatility_threshold = (
        0.65 * df["atr14_percent"] * math.sqrt(float(horizon_minutes))
    )
    df["label_threshold"] = np.maximum(0.0010, volatility_threshold)

    df["label"] = 0
    df.loc[df["future_return"] >= df["label_threshold"], "label"] = 1
    df.loc[df["future_return"] <= -df["label_threshold"], "label"] = 2

    # Avoid the noisy opening minutes and rows without a complete future horizon.
    latest_entry_minute = 375 - horizon_minutes
    df = df[
        (df["minute_from_open"] >= 10)
        & (df["minute_from_open"] <= latest_entry_minute)
    ]

    needed = FEATURE_COLUMNS + ["future_return", "label_threshold", "label"]
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=needed)
    df["label"] = df["label"].astype(int)
    return df.reset_index(drop=True)


def split_by_dates(dataset: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, List[str]]]:
    dates = sorted(dataset["date"].unique().tolist())
    if len(dates) < 20:
        raise RuntimeError(f"Only {len(dates)} usable dates; at least 20 are required")

    train_end = max(1, int(len(dates) * 0.70))
    validation_end = max(train_end + 1, int(len(dates) * 0.85))
    validation_end = min(validation_end, len(dates) - 1)

    train_dates = dates[:train_end]
    validation_dates = dates[train_end:validation_end]
    test_dates = dates[validation_end:]

    train = dataset[dataset["date"].isin(train_dates)].copy()
    validation = dataset[dataset["date"].isin(validation_dates)].copy()
    test = dataset[dataset["date"].isin(test_dates)].copy()

    date_map = {
        "train": train_dates,
        "validation": validation_dates,
        "test": test_dates,
    }
    return train, validation, test, date_map


def standardize(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    test: pd.DataFrame,
) -> Tuple[SplitData, SplitData, SplitData, np.ndarray, np.ndarray]:
    train_x = train[FEATURE_COLUMNS].to_numpy(dtype=np.float64)
    mean = train_x.mean(axis=0)
    scale = train_x.std(axis=0)
    scale = np.where(scale < 1e-10, 1.0, scale)

    def make(name: str, source: pd.DataFrame) -> SplitData:
        x = (source[FEATURE_COLUMNS].to_numpy(dtype=np.float64) - mean) / scale
        y = source["label"].to_numpy(dtype=np.int64)
        return SplitData(name=name, frame=source, x=x, y=y)

    return make("train", train), make("validation", validation), make("test", test), mean, scale


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    exp = np.exp(np.clip(shifted, -60.0, 60.0))
    return exp / exp.sum(axis=1, keepdims=True)


def cross_entropy(probabilities: np.ndarray, labels: np.ndarray) -> float:
    selected = probabilities[np.arange(len(labels)), labels]
    return float(-np.log(np.clip(selected, 1e-12, 1.0)).mean())


def class_weights(labels: np.ndarray) -> np.ndarray:
    counts = np.bincount(labels, minlength=3).astype(np.float64)
    counts = np.where(counts <= 0, 1.0, counts)
    weights = len(labels) / (3.0 * counts)
    # Prevent a very rare class from dominating training.
    return np.clip(weights, 0.5, 4.0)


def train_softmax(
    train: SplitData,
    validation: SplitData,
    epochs: int,
    learning_rate: float,
    l2: float,
) -> Tuple[np.ndarray, Dict[str, object]]:
    train_x = np.column_stack([np.ones(len(train.x)), train.x])
    validation_x = np.column_stack([np.ones(len(validation.x)), validation.x])
    weights = np.zeros((train_x.shape[1], 3), dtype=np.float64)
    best_weights = weights.copy()
    best_loss = float("inf")
    patience_checks = 18
    checks_without_improvement = 0
    weight_per_class = class_weights(train.y)
    sample_weights = weight_per_class[train.y]
    one_hot = np.eye(3, dtype=np.float64)[train.y]
    history: List[Dict[str, float]] = []

    for epoch in range(1, epochs + 1):
        probabilities = softmax(train_x @ weights)
        error = (probabilities - one_hot) * sample_weights[:, None]
        gradient = (train_x.T @ error) / sample_weights.sum()
        gradient[1:] += l2 * weights[1:]
        weights -= learning_rate * gradient

        if epoch == 1 or epoch % 10 == 0:
            validation_probabilities = softmax(validation_x @ weights)
            validation_loss = cross_entropy(validation_probabilities, validation.y)
            train_loss = cross_entropy(probabilities, train.y)
            history.append(
                {
                    "epoch": float(epoch),
                    "train_loss": train_loss,
                    "validation_loss": validation_loss,
                }
            )

            if validation_loss < best_loss - 1e-5:
                best_loss = validation_loss
                best_weights = weights.copy()
                checks_without_improvement = 0
            else:
                checks_without_improvement += 1
                if checks_without_improvement >= patience_checks:
                    break

    report = {
        "epochs_completed": int(history[-1]["epoch"] if history else 0),
        "best_validation_loss": float(best_loss),
        "class_weights": weight_per_class.tolist(),
        "history_tail": history[-10:],
    }
    return best_weights, report


def probabilities_for(split: SplitData, weights: np.ndarray) -> np.ndarray:
    x = np.column_stack([np.ones(len(split.x)), split.x])
    return softmax(x @ weights)


def apply_confidence_gate(probabilities: np.ndarray, gate: float) -> np.ndarray:
    predictions = probabilities.argmax(axis=1).astype(np.int64)
    confidence = probabilities.max(axis=1)
    predictions[(predictions != 0) & (confidence < gate)] = 0
    return predictions


def confusion_matrix(labels: np.ndarray, predictions: np.ndarray) -> np.ndarray:
    matrix = np.zeros((3, 3), dtype=np.int64)
    for true_label, predicted_label in zip(labels, predictions):
        matrix[int(true_label), int(predicted_label)] += 1
    return matrix


def metric_report(labels: np.ndarray, predictions: np.ndarray) -> Dict[str, object]:
    matrix = confusion_matrix(labels, predictions)
    accuracy = float((labels == predictions).mean())
    recalls = []
    precisions = []
    for class_index in range(3):
        true_total = matrix[class_index, :].sum()
        predicted_total = matrix[:, class_index].sum()
        recalls.append(float(matrix[class_index, class_index] / true_total) if true_total else 0.0)
        precisions.append(float(matrix[class_index, class_index] / predicted_total) if predicted_total else 0.0)

    directional_mask = predictions != 0
    directional_coverage = float(directional_mask.mean())
    directional_precision = (
        float((labels[directional_mask] == predictions[directional_mask]).mean())
        if directional_mask.any()
        else 0.0
    )

    return {
        "rows": int(len(labels)),
        "accuracy": accuracy,
        "macro_recall": float(np.mean(recalls)),
        "class_recall": dict(zip(CLASS_NAMES.tolist(), recalls)),
        "class_precision": dict(zip(CLASS_NAMES.tolist(), precisions)),
        "directional_coverage": directional_coverage,
        "directional_precision": directional_precision,
        "true_distribution": {
            CLASS_NAMES[index]: int((labels == index).sum()) for index in range(3)
        },
        "predicted_distribution": {
            CLASS_NAMES[index]: int((predictions == index).sum()) for index in range(3)
        },
        "confusion_matrix_rows_true_columns_predicted": matrix.tolist(),
    }


def select_confidence_gate(probabilities: np.ndarray, labels: np.ndarray) -> Tuple[float, Dict[str, object]]:
    best_gate = 0.34
    best_score = -1.0
    best_metrics: Dict[str, object] = {}

    for gate in np.arange(0.34, 0.751, 0.02):
        predictions = apply_confidence_gate(probabilities, float(gate))
        metrics = metric_report(labels, predictions)
        coverage = float(metrics["directional_coverage"])
        directional_precision = float(metrics["directional_precision"])
        macro_recall = float(metrics["macro_recall"])
        coverage_bonus = min(coverage / 0.20, 1.0)
        score = macro_recall + 0.15 * directional_precision + 0.05 * coverage_bonus
        if score > best_score:
            best_score = score
            best_gate = float(gate)
            best_metrics = metrics

    best_metrics = dict(best_metrics)
    best_metrics["selection_score"] = float(best_score)
    return best_gate, best_metrics


def save_outputs(
    output_dir: Path,
    dataset: pd.DataFrame,
    train: SplitData,
    validation: SplitData,
    test: SplitData,
    date_map: Dict[str, List[str]],
    mean: np.ndarray,
    scale: np.ndarray,
    weights: np.ndarray,
    confidence_gate: float,
    training_report: Dict[str, object],
    validation_metrics: Dict[str, object],
    test_probabilities: np.ndarray,
    test_predictions: np.ndarray,
    horizon_minutes: int,
    source_files: Sequence[Path],
) -> Tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "nifty_direction_softmax_v1.npz"
    metadata_path = output_dir / "nifty_direction_softmax_v1.json"
    predictions_path = output_dir / "nifty_direction_softmax_v1_test_predictions.csv"

    np.savez_compressed(
        model_path,
        weights=weights,
        feature_mean=mean,
        feature_scale=scale,
        feature_names=np.array(FEATURE_COLUMNS, dtype=object),
        class_names=CLASS_NAMES,
        confidence_gate=np.array([confidence_gate], dtype=np.float64),
        horizon_minutes=np.array([horizon_minutes], dtype=np.int64),
    )

    test_metrics = metric_report(test.y, test_predictions)
    metadata = {
        "model_version": MODEL_VERSION,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "mode": "SHADOW_ONLY",
        "order_execution": False,
        "model_type": "weighted_multiclass_softmax_regression_numpy",
        "symbol": "NIFTY",
        "timeframe": "ONE_MINUTE",
        "horizon_minutes": horizon_minutes,
        "label_rule": {
            "CE": "future_return >= max(0.10%, 0.65 * ATR14_percent * sqrt(horizon))",
            "PE": "future_return <= -max(0.10%, 0.65 * ATR14_percent * sqrt(horizon))",
            "NO_TRADE": "otherwise",
        },
        "feature_names": FEATURE_COLUMNS,
        "confidence_gate": confidence_gate,
        "source_file_count": len(source_files),
        "source_files": [str(path) for path in source_files],
        "dataset_rows": int(len(dataset)),
        "date_splits": date_map,
        "row_splits": {
            "train": int(len(train.frame)),
            "validation": int(len(validation.frame)),
            "test": int(len(test.frame)),
        },
        "training": training_report,
        "validation_metrics": validation_metrics,
        "test_metrics": test_metrics,
        "limitations": [
            "Prototype trained on a short May-July 2026 period.",
            "NIFTY index volume is zero and is not used.",
            "Labels use future NIFTY spot movement, not option premium P&L.",
            "Model must remain shadow-only until longer walk-forward validation.",
        ],
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    prediction_frame = test.frame[
        ["timestamp", "date", "close", "future_close", "future_return", "label_threshold"]
    ].copy()
    prediction_frame["true_label"] = CLASS_NAMES[test.y]
    prediction_frame["predicted_label"] = CLASS_NAMES[test_predictions]
    prediction_frame["confidence"] = test_probabilities.max(axis=1)
    prediction_frame["prob_no_trade"] = test_probabilities[:, 0]
    prediction_frame["prob_ce"] = test_probabilities[:, 1]
    prediction_frame["prob_pe"] = test_probabilities[:, 2]
    prediction_frame.to_csv(predictions_path, index=False)

    return model_path, metadata_path, predictions_path


def print_metrics(title: str, metrics: Dict[str, object]) -> None:
    print(f"\n=== {title} ===")
    print(f"rows = {metrics['rows']}")
    print(f"accuracy = {metrics['accuracy']:.4f}")
    print(f"macro_recall = {metrics['macro_recall']:.4f}")
    print(f"directional_coverage = {metrics['directional_coverage']:.4f}")
    print(f"directional_precision = {metrics['directional_precision']:.4f}")
    print("true_distribution =", metrics["true_distribution"])
    print("predicted_distribution =", metrics["predicted_distribution"])
    print("confusion_matrix =", metrics["confusion_matrix_rows_true_columns_predicted"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the NIFTY shadow direction model")
    parser.add_argument("--horizon", type=int, default=15, help="Future horizon in minutes")
    parser.add_argument("--epochs", type=int, default=500, help="Maximum training epochs")
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--l2", type=float, default=0.001)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.horizon < 5 or args.horizon > 60:
        raise SystemExit("--horizon must be between 5 and 60 minutes")

    files = discover_spot_files(DEFAULT_SPOT_DIRS)
    print("=== NIFTY SHADOW TRAINER ===")
    print("model_version =", MODEL_VERSION)
    print("source_files =", len(files))
    if files:
        print("source_from =", files[0].name)
        print("source_to   =", files[-1].name)
    if len(files) < 20:
        raise SystemExit("Not enough daily NIFTY candle files")

    candles = load_candles(files)
    dataset = build_dataset(candles, args.horizon)
    train_frame, validation_frame, test_frame, date_map = split_by_dates(dataset)
    train, validation, test, mean, scale = standardize(
        train_frame,
        validation_frame,
        test_frame,
    )

    print("raw_candles =", len(candles))
    print("usable_rows =", len(dataset))
    print("train_dates =", len(date_map["train"]), date_map["train"][0], "to", date_map["train"][-1])
    print("validation_dates =", len(date_map["validation"]), date_map["validation"][0], "to", date_map["validation"][-1])
    print("test_dates =", len(date_map["test"]), date_map["test"][0], "to", date_map["test"][-1])

    weights, training_report = train_softmax(
        train,
        validation,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        l2=args.l2,
    )

    validation_probabilities = probabilities_for(validation, weights)
    confidence_gate, validation_metrics = select_confidence_gate(
        validation_probabilities,
        validation.y,
    )
    validation_predictions = apply_confidence_gate(validation_probabilities, confidence_gate)
    validation_metrics = metric_report(validation.y, validation_predictions)

    test_probabilities = probabilities_for(test, weights)
    test_predictions = apply_confidence_gate(test_probabilities, confidence_gate)
    test_metrics = metric_report(test.y, test_predictions)

    print("epochs_completed =", training_report["epochs_completed"])
    print("best_validation_loss =", round(float(training_report["best_validation_loss"]), 6))
    print("confidence_gate =", round(confidence_gate, 4))
    print_metrics("VALIDATION", validation_metrics)
    print_metrics("UNSEEN TEST", test_metrics)

    model_path, metadata_path, predictions_path = save_outputs(
        output_dir=args.output_dir,
        dataset=dataset,
        train=train,
        validation=validation,
        test=test,
        date_map=date_map,
        mean=mean,
        scale=scale,
        weights=weights,
        confidence_gate=confidence_gate,
        training_report=training_report,
        validation_metrics=validation_metrics,
        test_probabilities=test_probabilities,
        test_predictions=test_predictions,
        horizon_minutes=args.horizon,
        source_files=files,
    )

    print("\n=== SAVED ===")
    print("model =", model_path)
    print("metadata =", metadata_path)
    print("test_predictions =", predictions_path)
    print("mode = SHADOW_ONLY")
    print("order_execution = OFF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
