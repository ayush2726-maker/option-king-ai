"""Train a two-stage NIFTY shadow model using pandas and NumPy only.

Stage 1 predicts whether a clean directional opportunity exists.
Stage 2 predicts CE versus PE only for labelled opportunities.
Labels use future maximum favourable/adverse NIFTY movement, not only the
future closing price. Outputs remain research-only and never import app.py.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd

from train_nifty_shadow_model import (
    DEFAULT_SPOT_DIRS,
    FEATURE_COLUMNS,
    discover_spot_files,
    load_candles,
)


MODEL_VERSION = "nifty-two-stage-shadow-0.2.0"
OUTPUT_DIR = Path("data/ml_models")
CLASS_NAMES = np.array(["NO_TRADE", "CE", "PE"], dtype=object)
EXTRA_FEATURES = [
    "trend_strength_atr",
    "upper_wick_percent",
    "lower_wick_percent",
    "return_acceleration",
]
ALL_FEATURES = FEATURE_COLUMNS + EXTRA_FEATURES


def grouped_transform(df: pd.DataFrame, column: str, function) -> pd.Series:
    return df.groupby("date", sort=False)[column].transform(function)


def future_window(series: pd.Series, horizon: int, operation: str) -> pd.Series:
    shifted = series.shift(-1)
    rolling = shifted.rolling(horizon, min_periods=horizon)
    result = rolling.max() if operation == "max" else rolling.min()
    return result.shift(-(horizon - 1))


def build_dataset(candles: pd.DataFrame, horizon: int) -> pd.DataFrame:
    df = candles.copy()
    group = df.groupby("date", sort=False)

    for periods in (1, 3, 5, 10):
        df[f"return_{periods}"] = group["close"].pct_change(periods, fill_method=None)

    df["ema9"] = grouped_transform(
        df, "close", lambda s: s.ewm(span=9, adjust=False).mean()
    )
    df["ema21"] = grouped_transform(
        df, "close", lambda s: s.ewm(span=21, adjust=False).mean()
    )
    df["ema_gap_9_21"] = (df["ema9"] - df["ema21"]) / df["close"]
    df["close_vs_ema9"] = (df["close"] - df["ema9"]) / df["close"]
    df["close_vs_ema21"] = (df["close"] - df["ema21"]) / df["close"]

    previous_close = group["close"].shift(1)
    df["true_range"] = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr14"] = grouped_transform(
        df, "true_range", lambda s: s.rolling(14, min_periods=14).mean()
    )
    df["atr14_percent"] = df["atr14"] / df["close"]

    delta = group["close"].diff()
    df["gain"] = delta.clip(lower=0)
    df["loss"] = (-delta).clip(lower=0)
    avg_gain = grouped_transform(
        df, "gain", lambda s: s.rolling(14, min_periods=14).mean()
    )
    avg_loss = grouped_transform(
        df, "loss", lambda s: s.rolling(14, min_periods=14).mean()
    )
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi = rsi.where(avg_loss > 0, 100.0)
    rsi = rsi.where(avg_gain > 0, 0.0)
    df["rsi14_scaled"] = (rsi - 50.0) / 50.0

    df["range_percent"] = (df["high"] - df["low"]) / df["close"]
    df["body_percent"] = (df["close"] - df["open"]) / df["open"]
    df["rolling_vol_5"] = grouped_transform(
        df, "return_1", lambda s: s.rolling(5, min_periods=5).std(ddof=0)
    )
    df["rolling_vol_15"] = grouped_transform(
        df, "return_1", lambda s: s.rolling(15, min_periods=15).std(ddof=0)
    )

    day_open = group["open"].transform("first")
    df["distance_day_open"] = (df["close"] - day_open) / day_open
    rolling_high = grouped_transform(
        df, "high", lambda s: s.rolling(15, min_periods=15).max()
    )
    rolling_low = grouped_transform(
        df, "low", lambda s: s.rolling(15, min_periods=15).min()
    )
    range_15 = (rolling_high - rolling_low).replace(0, np.nan)
    df["position_in_15_range"] = ((df["close"] - rolling_low) / range_15) * 2.0 - 1.0

    minute_from_open = (df["hour"] * 60 + df["minute"]) - 555
    df["minute_from_open"] = minute_from_open
    df["minute_from_open_scaled"] = (minute_from_open - 187.5) / 187.5

    candle_top = df[["open", "close"]].max(axis=1)
    candle_bottom = df[["open", "close"]].min(axis=1)
    df["upper_wick_percent"] = (df["high"] - candle_top) / df["close"]
    df["lower_wick_percent"] = (candle_bottom - df["low"]) / df["close"]
    df["return_acceleration"] = df["return_3"] - df["return_10"] * 0.3
    df["trend_strength_atr"] = (
        (df["ema9"] - df["ema21"]) / df["atr14"].replace(0, np.nan)
    )

    future_high_parts = []
    future_low_parts = []
    for _, day in df.groupby("date", sort=False):
        future_high_parts.append(future_window(day["high"], horizon, "max"))
        future_low_parts.append(future_window(day["low"], horizon, "min"))
    df["future_high"] = pd.concat(future_high_parts).sort_index()
    df["future_low"] = pd.concat(future_low_parts).sort_index()

    df["up_mfe"] = (df["future_high"] / df["close"]) - 1.0
    df["down_mfe"] = (df["close"] / df["future_low"]) - 1.0
    df["threshold"] = np.maximum(0.0012, 0.90 * df["atr14_percent"] * np.sqrt(horizon))
    df["adverse_limit"] = np.maximum(0.0008, df["threshold"] * 0.80)

    ce = (
        (df["up_mfe"] >= df["threshold"])
        & (df["up_mfe"] >= df["down_mfe"] * 1.30)
        & (df["down_mfe"] <= df["adverse_limit"])
    )
    pe = (
        (df["down_mfe"] >= df["threshold"])
        & (df["down_mfe"] >= df["up_mfe"] * 1.30)
        & (df["up_mfe"] <= df["adverse_limit"])
    )

    df["label"] = 0
    df.loc[ce, "label"] = 1
    df.loc[pe, "label"] = 2
    df["opportunity_label"] = (df["label"] != 0).astype(int)
    df["direction_label"] = (df["label"] == 1).astype(int)

    latest_entry = 375 - horizon
    df = df[(df["minute_from_open"] >= 10) & (df["minute_from_open"] <= latest_entry)]
    required = ALL_FEATURES + [
        "future_high",
        "future_low",
        "up_mfe",
        "down_mfe",
        "threshold",
        "label",
    ]
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=required)
    return df.reset_index(drop=True)


def split_by_date(df: pd.DataFrame):
    dates = sorted(df["date"].unique().tolist())
    if len(dates) < 20:
        raise RuntimeError("At least 20 usable trading dates are required")
    train_end = int(len(dates) * 0.70)
    validation_end = min(int(len(dates) * 0.85), len(dates) - 1)
    train_dates = dates[:train_end]
    validation_dates = dates[train_end:validation_end]
    test_dates = dates[validation_end:]
    return (
        df[df["date"].isin(train_dates)].copy(),
        df[df["date"].isin(validation_dates)].copy(),
        df[df["date"].isin(test_dates)].copy(),
        {"train": train_dates, "validation": validation_dates, "test": test_dates},
    )


def sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-values))


def binary_loss(probabilities: np.ndarray, labels: np.ndarray, sample_weights: np.ndarray) -> float:
    probabilities = np.clip(probabilities, 1e-10, 1.0 - 1e-10)
    losses = -(labels * np.log(probabilities) + (1 - labels) * np.log(1 - probabilities))
    return float(np.average(losses, weights=sample_weights))


def fit_logistic(
    train_x: np.ndarray,
    train_y: np.ndarray,
    validation_x: np.ndarray,
    validation_y: np.ndarray,
    epochs: int,
    learning_rate: float,
    l2: float,
) -> Tuple[np.ndarray, Dict[str, object]]:
    train_x = np.column_stack([np.ones(len(train_x)), train_x])
    validation_x = np.column_stack([np.ones(len(validation_x)), validation_x])
    weights = np.zeros(train_x.shape[1], dtype=np.float64)

    count_0 = max(1, int((train_y == 0).sum()))
    count_1 = max(1, int((train_y == 1).sum()))
    class_weights = np.array(
        [len(train_y) / (2.0 * count_0), len(train_y) / (2.0 * count_1)],
        dtype=np.float64,
    )
    class_weights = np.clip(class_weights, 0.5, 4.0)
    sample_weights = class_weights[train_y]
    validation_sample_weights = np.ones(len(validation_y), dtype=np.float64)

    best_weights = weights.copy()
    best_loss = float("inf")
    patience = 20
    no_improvement = 0
    history: List[Dict[str, float]] = []

    for epoch in range(1, epochs + 1):
        probabilities = sigmoid(train_x @ weights)
        error = (probabilities - train_y) * sample_weights
        gradient = (train_x.T @ error) / sample_weights.sum()
        gradient[1:] += l2 * weights[1:]
        weights -= learning_rate * gradient

        if epoch == 1 or epoch % 10 == 0:
            validation_probabilities = sigmoid(validation_x @ weights)
            validation_loss = binary_loss(
                validation_probabilities,
                validation_y,
                validation_sample_weights,
            )
            train_loss = binary_loss(probabilities, train_y, sample_weights)
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
                no_improvement = 0
            else:
                no_improvement += 1
                if no_improvement >= patience:
                    break

    return best_weights, {
        "epochs_completed": int(history[-1]["epoch"] if history else 0),
        "best_validation_loss": float(best_loss),
        "class_weights": class_weights.tolist(),
        "history_tail": history[-8:],
    }


def prepare_features(train: pd.DataFrame, validation: pd.DataFrame, test: pd.DataFrame):
    raw_train = train[ALL_FEATURES].to_numpy(dtype=np.float64)
    mean = raw_train.mean(axis=0)
    scale = raw_train.std(axis=0)
    scale = np.where(scale < 1e-10, 1.0, scale)

    def transform(frame: pd.DataFrame) -> np.ndarray:
        return (frame[ALL_FEATURES].to_numpy(dtype=np.float64) - mean) / scale

    return transform(train), transform(validation), transform(test), mean, scale


def predict_binary(x: np.ndarray, weights: np.ndarray) -> np.ndarray:
    return sigmoid(np.column_stack([np.ones(len(x)), x]) @ weights)


def final_predictions(
    opportunity_probability: np.ndarray,
    ce_probability: np.ndarray,
    opportunity_threshold: float,
    direction_threshold: float,
) -> np.ndarray:
    predictions = np.zeros(len(opportunity_probability), dtype=np.int64)
    direction_confidence = np.maximum(ce_probability, 1.0 - ce_probability)
    allowed = (
        (opportunity_probability >= opportunity_threshold)
        & (direction_confidence >= direction_threshold)
    )
    predictions[allowed & (ce_probability >= 0.5)] = 1
    predictions[allowed & (ce_probability < 0.5)] = 2
    return predictions


def metrics(labels: np.ndarray, predictions: np.ndarray) -> Dict[str, object]:
    matrix = np.zeros((3, 3), dtype=np.int64)
    for true_label, predicted_label in zip(labels, predictions):
        matrix[int(true_label), int(predicted_label)] += 1

    directional = predictions != 0
    actual_opportunity = labels != 0
    correct_directional = directional & (predictions == labels)
    directional_count = int(directional.sum())
    directional_precision = (
        float(correct_directional.sum() / directional_count) if directional_count else 0.0
    )
    opportunity_recall = (
        float(correct_directional.sum() / actual_opportunity.sum())
        if actual_opportunity.any()
        else 0.0
    )
    coverage = float(directional.mean())

    per_direction_precision: Dict[str, float] = {}
    for index, name in ((1, "CE"), (2, "PE")):
        predicted_mask = predictions == index
        per_direction_precision[name] = (
            float(((labels == index) & predicted_mask).sum() / predicted_mask.sum())
            if predicted_mask.any()
            else 0.0
        )

    return {
        "rows": int(len(labels)),
        "accuracy": float((labels == predictions).mean()),
        "directional_count": directional_count,
        "directional_coverage": coverage,
        "directional_precision": directional_precision,
        "opportunity_recall": opportunity_recall,
        "per_direction_precision": per_direction_precision,
        "true_distribution": {
            CLASS_NAMES[i]: int((labels == i).sum()) for i in range(3)
        },
        "predicted_distribution": {
            CLASS_NAMES[i]: int((predictions == i).sum()) for i in range(3)
        },
        "confusion_matrix_rows_true_columns_predicted": matrix.tolist(),
    }


def choose_thresholds(
    labels: np.ndarray,
    opportunity_probability: np.ndarray,
    ce_probability: np.ndarray,
) -> Tuple[float, float, Dict[str, object]]:
    best = None
    minimum_count = max(50, int(len(labels) * 0.03))

    for opportunity_threshold in np.arange(0.45, 0.91, 0.05):
        for direction_threshold in np.arange(0.50, 0.81, 0.05):
            predictions = final_predictions(
                opportunity_probability,
                ce_probability,
                float(opportunity_threshold),
                float(direction_threshold),
            )
            report = metrics(labels, predictions)
            if report["directional_count"] < minimum_count:
                continue
            score = (
                float(report["directional_precision"])
                + 0.20 * float(report["opportunity_recall"])
                + 0.05 * min(float(report["directional_coverage"]) / 0.15, 1.0)
            )
            candidate = (score, float(opportunity_threshold), float(direction_threshold), report)
            if best is None or candidate[0] > best[0]:
                best = candidate

    if best is None:
        opportunity_threshold = 0.60
        direction_threshold = 0.60
        predictions = final_predictions(
            opportunity_probability,
            ce_probability,
            opportunity_threshold,
            direction_threshold,
        )
        return opportunity_threshold, direction_threshold, metrics(labels, predictions)

    return best[1], best[2], best[3]


def print_report(title: str, report: Dict[str, object]) -> None:
    print(f"\n=== {title} ===")
    for key in (
        "rows",
        "accuracy",
        "directional_count",
        "directional_coverage",
        "directional_precision",
        "opportunity_recall",
    ):
        print(f"{key} = {report[key]}")
    print("per_direction_precision =", report["per_direction_precision"])
    print("true_distribution =", report["true_distribution"])
    print("predicted_distribution =", report["predicted_distribution"])
    print("confusion_matrix =", report["confusion_matrix_rows_true_columns_predicted"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon", type=int, default=15)
    parser.add_argument("--epochs", type=int, default=700)
    parser.add_argument("--learning-rate", type=float, default=0.04)
    parser.add_argument("--l2", type=float, default=0.001)
    args = parser.parse_args()

    files = discover_spot_files(DEFAULT_SPOT_DIRS)
    candles = load_candles(files)
    dataset = build_dataset(candles, args.horizon)
    train, validation, test, date_map = split_by_date(dataset)
    train_x, validation_x, test_x, mean, scale = prepare_features(train, validation, test)

    opportunity_train_y = train["opportunity_label"].to_numpy(dtype=np.int64)
    opportunity_validation_y = validation["opportunity_label"].to_numpy(dtype=np.int64)
    opportunity_weights, opportunity_training = fit_logistic(
        train_x,
        opportunity_train_y,
        validation_x,
        opportunity_validation_y,
        args.epochs,
        args.learning_rate,
        args.l2,
    )

    direction_train_mask = train["opportunity_label"].to_numpy(dtype=bool)
    direction_validation_mask = validation["opportunity_label"].to_numpy(dtype=bool)
    if direction_train_mask.sum() < 100 or direction_validation_mask.sum() < 20:
        raise RuntimeError("Too few directional opportunity rows for stage 2")

    direction_weights, direction_training = fit_logistic(
        train_x[direction_train_mask],
        train.loc[direction_train_mask, "direction_label"].to_numpy(dtype=np.int64),
        validation_x[direction_validation_mask],
        validation.loc[direction_validation_mask, "direction_label"].to_numpy(dtype=np.int64),
        args.epochs,
        args.learning_rate,
        args.l2,
    )

    validation_opportunity_probability = predict_binary(validation_x, opportunity_weights)
    validation_ce_probability = predict_binary(validation_x, direction_weights)
    opportunity_threshold, direction_threshold, validation_report = choose_thresholds(
        validation["label"].to_numpy(dtype=np.int64),
        validation_opportunity_probability,
        validation_ce_probability,
    )
    validation_predictions = final_predictions(
        validation_opportunity_probability,
        validation_ce_probability,
        opportunity_threshold,
        direction_threshold,
    )
    validation_report = metrics(
        validation["label"].to_numpy(dtype=np.int64), validation_predictions
    )

    test_opportunity_probability = predict_binary(test_x, opportunity_weights)
    test_ce_probability = predict_binary(test_x, direction_weights)
    test_predictions = final_predictions(
        test_opportunity_probability,
        test_ce_probability,
        opportunity_threshold,
        direction_threshold,
    )
    test_labels = test["label"].to_numpy(dtype=np.int64)
    test_report = metrics(test_labels, test_predictions)

    ce_precision = float(test_report["per_direction_precision"]["CE"])
    pe_precision = float(test_report["per_direction_precision"]["PE"])
    approved = (
        float(test_report["directional_precision"]) >= 0.55
        and float(test_report["directional_coverage"]) >= 0.05
        and int(test_report["directional_count"]) >= 100
        and ce_precision >= 0.45
        and pe_precision >= 0.45
    )
    approval_status = "SHADOW_CANDIDATE" if approved else "REJECTED"

    print("=== NIFTY TWO-STAGE SHADOW TRAINER ===")
    print("model_version =", MODEL_VERSION)
    print("source_files =", len(files))
    print("raw_candles =", len(candles))
    print("usable_rows =", len(dataset))
    print("train_dates =", len(date_map["train"]), date_map["train"][0], "to", date_map["train"][-1])
    print("validation_dates =", len(date_map["validation"]), date_map["validation"][0], "to", date_map["validation"][-1])
    print("test_dates =", len(date_map["test"]), date_map["test"][0], "to", date_map["test"][-1])
    print("opportunity_epochs =", opportunity_training["epochs_completed"])
    print("direction_epochs =", direction_training["epochs_completed"])
    print("opportunity_threshold =", round(opportunity_threshold, 4))
    print("direction_threshold =", round(direction_threshold, 4))
    print_report("VALIDATION", validation_report)
    print_report("UNSEEN TEST", test_report)
    print("\nAPPROVAL_STATUS =", approval_status)
    print("order_execution = OFF")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = OUTPUT_DIR / "nifty_two_stage_shadow_v2.npz"
    metadata_path = OUTPUT_DIR / "nifty_two_stage_shadow_v2.json"
    predictions_path = OUTPUT_DIR / "nifty_two_stage_shadow_v2_test_predictions.csv"

    np.savez_compressed(
        model_path,
        opportunity_weights=opportunity_weights,
        direction_weights=direction_weights,
        feature_mean=mean,
        feature_scale=scale,
        feature_names=np.array(ALL_FEATURES, dtype=object),
        opportunity_threshold=np.array([opportunity_threshold]),
        direction_threshold=np.array([direction_threshold]),
        horizon_minutes=np.array([args.horizon]),
    )

    metadata = {
        "model_version": MODEL_VERSION,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "approval_status": approval_status,
        "approved_for_shadow": bool(approved),
        "approved_for_paper": False,
        "approved_for_live": False,
        "order_execution": False,
        "source_file_count": len(files),
        "dataset_rows": len(dataset),
        "horizon_minutes": args.horizon,
        "feature_names": ALL_FEATURES,
        "date_splits": date_map,
        "row_splits": {
            "train": len(train),
            "validation": len(validation),
            "test": len(test),
        },
        "label_method": {
            "description": "future maximum favourable/adverse NIFTY spot movement",
            "minimum_move": "max(0.12%, 0.90 * ATR14_percent * sqrt(horizon))",
            "dominance_ratio": 1.30,
            "adverse_limit": "max(0.08%, 0.80 * minimum_move)",
        },
        "thresholds": {
            "opportunity": opportunity_threshold,
            "direction": direction_threshold,
        },
        "opportunity_training": opportunity_training,
        "direction_training": direction_training,
        "validation_metrics": validation_report,
        "test_metrics": test_report,
        "limitations": [
            "Only a short May-July 2026 market period is available.",
            "Labels use NIFTY spot movement, not real option premium P&L.",
            "No model may control paper or live orders from this trainer.",
        ],
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    output = test[[
        "timestamp",
        "date",
        "close",
        "future_high",
        "future_low",
        "up_mfe",
        "down_mfe",
        "threshold",
    ]].copy()
    output["true_label"] = CLASS_NAMES[test_labels]
    output["predicted_label"] = CLASS_NAMES[test_predictions]
    output["opportunity_probability"] = test_opportunity_probability
    output["ce_probability"] = test_ce_probability
    output["direction_confidence"] = np.maximum(
        test_ce_probability, 1.0 - test_ce_probability
    )
    output.to_csv(predictions_path, index=False)

    marker_path = OUTPUT_DIR / "nifty_two_stage_shadow_v2_STATUS.txt"
    marker_path.write_text(
        f"{approval_status}\n"
        "PAPER=BLOCKED\n"
        "LIVE=BLOCKED\n"
        f"TEST_DIRECTIONAL_PRECISION={test_report['directional_precision']}\n"
        f"TEST_DIRECTIONAL_COVERAGE={test_report['directional_coverage']}\n",
        encoding="utf-8",
    )

    print("\nmodel =", model_path)
    print("metadata =", metadata_path)
    print("test_predictions =", predictions_path)
    print("status_marker =", marker_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
