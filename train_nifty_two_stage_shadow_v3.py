"""Calibrated two-stage NIFTY shadow trainer for the expanded candle set.

This V3 keeps the MFE/MAE labels from V2 but fixes the permissive threshold
search that allowed every candle to become a trade. It uses mild class
weighting, validation-quantile thresholds, a strict NO_TRADE gate, and
automatic rejection. It never imports app.py or executes orders.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from train_nifty_shadow_model import discover_spot_files, load_candles
from train_nifty_two_stage_shadow import (
    ALL_FEATURES,
    CLASS_NAMES,
    DEFAULT_SPOT_DIRS,
    build_dataset,
    final_predictions,
    metrics,
    predict_binary,
    prepare_features,
    print_report,
    split_by_date,
)


MODEL_VERSION = "nifty-two-stage-shadow-0.3.0"
OUTPUT_DIR = Path("data/ml_models")


def sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-values))


def weighted_binary_loss(
    probabilities: np.ndarray,
    labels: np.ndarray,
    sample_weights: np.ndarray,
) -> float:
    probabilities = np.clip(probabilities, 1e-10, 1.0 - 1e-10)
    losses = -(
        labels * np.log(probabilities)
        + (1 - labels) * np.log(1 - probabilities)
    )
    return float(np.average(losses, weights=sample_weights))


def mild_class_weights(labels: np.ndarray, maximum: float) -> np.ndarray:
    count_zero = max(1, int((labels == 0).sum()))
    count_one = max(1, int((labels == 1).sum()))
    ratio = count_zero / count_one

    if ratio >= 1.0:
        weights = np.array([1.0, min(maximum, np.sqrt(ratio))])
    else:
        weights = np.array([min(maximum, np.sqrt(1.0 / ratio)), 1.0])

    return weights / weights.mean()


def fit_logistic_calibrated(
    train_x: np.ndarray,
    train_y: np.ndarray,
    validation_x: np.ndarray,
    validation_y: np.ndarray,
    epochs: int,
    learning_rate: float,
    l2: float,
    maximum_class_weight: float,
) -> Tuple[np.ndarray, Dict[str, object]]:
    train_design = np.column_stack([np.ones(len(train_x)), train_x])
    validation_design = np.column_stack([np.ones(len(validation_x)), validation_x])
    weights = np.zeros(train_design.shape[1], dtype=np.float64)

    per_class = mild_class_weights(train_y, maximum_class_weight)
    train_sample_weights = per_class[train_y]
    validation_sample_weights = np.ones(len(validation_y), dtype=np.float64)

    best_weights = weights.copy()
    best_loss = float("inf")
    checks_without_improvement = 0
    history: List[Dict[str, float]] = []

    for epoch in range(1, epochs + 1):
        probabilities = sigmoid(train_design @ weights)
        error = (probabilities - train_y) * train_sample_weights
        gradient = (train_design.T @ error) / train_sample_weights.sum()
        gradient[1:] += l2 * weights[1:]
        weights -= learning_rate * gradient

        if epoch == 1 or epoch % 10 == 0:
            validation_probabilities = sigmoid(validation_design @ weights)
            validation_loss = weighted_binary_loss(
                validation_probabilities,
                validation_y,
                validation_sample_weights,
            )
            train_loss = weighted_binary_loss(
                probabilities,
                train_y,
                train_sample_weights,
            )
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
                if checks_without_improvement >= 25:
                    break

    return best_weights, {
        "epochs_completed": int(history[-1]["epoch"] if history else 0),
        "best_validation_loss": float(best_loss),
        "class_weights": per_class.tolist(),
        "history_tail": history[-10:],
    }


def unique_thresholds(values: np.ndarray, quantiles: List[float], fixed: List[float]) -> List[float]:
    candidates = list(fixed)
    for quantile in quantiles:
        candidates.append(float(np.quantile(values, quantile)))
    return sorted({round(float(value), 6) for value in candidates if np.isfinite(value)})


def choose_strict_thresholds(
    labels: np.ndarray,
    opportunity_probability: np.ndarray,
    ce_probability: np.ndarray,
) -> Tuple[float, float, Dict[str, object]]:
    direction_confidence = np.maximum(ce_probability, 1.0 - ce_probability)

    opportunity_candidates = unique_thresholds(
        opportunity_probability,
        [0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.93, 0.95, 0.97, 0.98, 0.99],
        [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80],
    )
    direction_candidates = unique_thresholds(
        direction_confidence,
        [0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.93, 0.95, 0.97, 0.98],
        [0.55, 0.58, 0.60, 0.62, 0.65, 0.68, 0.70, 0.75, 0.80, 0.85],
    )

    minimum_count = max(100, int(len(labels) * 0.03))
    maximum_coverage = 0.35
    best = None

    for opportunity_threshold in opportunity_candidates:
        for direction_threshold in direction_candidates:
            predictions = final_predictions(
                opportunity_probability,
                ce_probability,
                opportunity_threshold,
                direction_threshold,
            )
            report = metrics(labels, predictions)
            count = int(report["directional_count"])
            coverage = float(report["directional_coverage"])
            if count < minimum_count or coverage > maximum_coverage:
                continue

            predicted = report["predicted_distribution"]
            if int(predicted["CE"]) < 20 or int(predicted["PE"]) < 20:
                continue

            precision = float(report["directional_precision"])
            recall = float(report["opportunity_recall"])
            ce_precision = float(report["per_direction_precision"]["CE"])
            pe_precision = float(report["per_direction_precision"]["PE"])
            direction_balance = min(
                int(predicted["CE"]), int(predicted["PE"])
            ) / max(int(predicted["CE"]), int(predicted["PE"]), 1)

            coverage_bonus = min(coverage / 0.12, 1.0)
            score = (
                precision
                + 0.12 * recall
                + 0.05 * coverage_bonus
                + 0.04 * min(ce_precision, pe_precision)
                + 0.02 * direction_balance
            )

            candidate = (
                score,
                opportunity_threshold,
                direction_threshold,
                report,
            )
            if best is None or candidate[0] > best[0]:
                best = candidate

    if best is None:
        opportunity_threshold = float(np.quantile(opportunity_probability, 0.90))
        direction_threshold = max(
            0.60,
            float(np.quantile(direction_confidence, 0.75)),
        )
        predictions = final_predictions(
            opportunity_probability,
            ce_probability,
            opportunity_threshold,
            direction_threshold,
        )
        return (
            opportunity_threshold,
            direction_threshold,
            metrics(labels, predictions),
        )

    return best[1], best[2], best[3]


def probability_summary(values: np.ndarray) -> Dict[str, float]:
    return {
        str(quantile): float(np.quantile(values, quantile))
        for quantile in (0.0, 0.05, 0.25, 0.50, 0.75, 0.95, 1.0)
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon", type=int, default=15)
    parser.add_argument("--epochs", type=int, default=900)
    parser.add_argument("--learning-rate", type=float, default=0.035)
    parser.add_argument("--l2", type=float, default=0.0015)
    args = parser.parse_args()

    files = discover_spot_files(DEFAULT_SPOT_DIRS)
    candles = load_candles(files)
    dataset = build_dataset(candles, args.horizon)
    train, validation, test, date_map = split_by_date(dataset)
    train_x, validation_x, test_x, mean, scale = prepare_features(
        train, validation, test
    )

    opportunity_train_y = train["opportunity_label"].to_numpy(dtype=np.int64)
    opportunity_validation_y = validation["opportunity_label"].to_numpy(dtype=np.int64)
    opportunity_weights, opportunity_training = fit_logistic_calibrated(
        train_x,
        opportunity_train_y,
        validation_x,
        opportunity_validation_y,
        args.epochs,
        args.learning_rate,
        args.l2,
        maximum_class_weight=2.5,
    )

    train_direction_mask = train["opportunity_label"].to_numpy(dtype=bool)
    validation_direction_mask = validation["opportunity_label"].to_numpy(dtype=bool)
    direction_weights, direction_training = fit_logistic_calibrated(
        train_x[train_direction_mask],
        train.loc[train_direction_mask, "direction_label"].to_numpy(dtype=np.int64),
        validation_x[validation_direction_mask],
        validation.loc[validation_direction_mask, "direction_label"].to_numpy(dtype=np.int64),
        args.epochs,
        args.learning_rate,
        args.l2,
        maximum_class_weight=1.8,
    )

    validation_opportunity = predict_binary(validation_x, opportunity_weights)
    validation_ce = predict_binary(validation_x, direction_weights)
    opportunity_threshold, direction_threshold, _ = choose_strict_thresholds(
        validation["label"].to_numpy(dtype=np.int64),
        validation_opportunity,
        validation_ce,
    )
    validation_predictions = final_predictions(
        validation_opportunity,
        validation_ce,
        opportunity_threshold,
        direction_threshold,
    )
    validation_report = metrics(
        validation["label"].to_numpy(dtype=np.int64),
        validation_predictions,
    )

    test_opportunity = predict_binary(test_x, opportunity_weights)
    test_ce = predict_binary(test_x, direction_weights)
    test_predictions = final_predictions(
        test_opportunity,
        test_ce,
        opportunity_threshold,
        direction_threshold,
    )
    test_labels = test["label"].to_numpy(dtype=np.int64)
    test_report = metrics(test_labels, test_predictions)

    baseline_accuracy = float((test_labels == 0).mean())
    ce_precision = float(test_report["per_direction_precision"]["CE"])
    pe_precision = float(test_report["per_direction_precision"]["PE"])
    approved = (
        float(test_report["directional_precision"]) >= 0.55
        and float(test_report["directional_coverage"]) >= 0.03
        and float(test_report["directional_coverage"]) <= 0.35
        and int(test_report["directional_count"]) >= 150
        and ce_precision >= 0.45
        and pe_precision >= 0.45
        and int(test_report["predicted_distribution"]["NO_TRADE"]) > 0
    )
    approval_status = "SHADOW_CANDIDATE" if approved else "REJECTED"

    print("=== NIFTY TWO-STAGE CALIBRATED V3 ===")
    print("model_version =", MODEL_VERSION)
    print("source_files =", len(files))
    print("raw_candles =", len(candles))
    print("usable_rows =", len(dataset))
    print("train_dates =", len(date_map["train"]), date_map["train"][0], "to", date_map["train"][-1])
    print("validation_dates =", len(date_map["validation"]), date_map["validation"][0], "to", date_map["validation"][-1])
    print("test_dates =", len(date_map["test"]), date_map["test"][0], "to", date_map["test"][-1])
    print("opportunity_epochs =", opportunity_training["epochs_completed"])
    print("direction_epochs =", direction_training["epochs_completed"])
    print("opportunity_threshold =", round(opportunity_threshold, 6))
    print("direction_threshold =", round(direction_threshold, 6))
    print("always_NO_TRADE_test_baseline =", round(baseline_accuracy, 6))
    print("validation_opportunity_probability =", probability_summary(validation_opportunity))
    print("test_opportunity_probability =", probability_summary(test_opportunity))
    print_report("VALIDATION", validation_report)
    print_report("UNSEEN TEST", test_report)
    print("\nAPPROVAL_STATUS =", approval_status)
    print("paper = BLOCKED")
    print("live = BLOCKED")
    print("order_execution = OFF")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = OUTPUT_DIR / "nifty_two_stage_calibrated_v3.npz"
    metadata_path = OUTPUT_DIR / "nifty_two_stage_calibrated_v3.json"
    predictions_path = OUTPUT_DIR / "nifty_two_stage_calibrated_v3_test_predictions.csv"
    marker_path = OUTPUT_DIR / "nifty_two_stage_calibrated_v3_STATUS.txt"

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
        "raw_candles": len(candles),
        "dataset_rows": len(dataset),
        "date_splits": date_map,
        "row_splits": {
            "train": len(train),
            "validation": len(validation),
            "test": len(test),
        },
        "thresholds": {
            "opportunity": opportunity_threshold,
            "direction": direction_threshold,
        },
        "always_no_trade_test_baseline": baseline_accuracy,
        "opportunity_training": opportunity_training,
        "direction_training": direction_training,
        "validation_metrics": validation_report,
        "test_metrics": test_report,
        "validation_opportunity_probability": probability_summary(validation_opportunity),
        "test_opportunity_probability": probability_summary(test_opportunity),
        "limitations": [
            "Linear prototype; tree-based validation is still required.",
            "Labels use NIFTY spot MFE/MAE rather than actual option premium P&L.",
            "Paper and live integration are always blocked by this trainer.",
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
    output["opportunity_probability"] = test_opportunity
    output["ce_probability"] = test_ce
    output["direction_confidence"] = np.maximum(test_ce, 1.0 - test_ce)
    output.to_csv(predictions_path, index=False)

    marker_path.write_text(
        f"{approval_status}\n"
        "PAPER=BLOCKED\n"
        "LIVE=BLOCKED\n"
        f"TEST_DIRECTIONAL_PRECISION={test_report['directional_precision']}\n"
        f"TEST_DIRECTIONAL_COVERAGE={test_report['directional_coverage']}\n"
        f"TEST_DIRECTIONAL_COUNT={test_report['directional_count']}\n",
        encoding="utf-8",
    )

    print("\nmodel =", model_path)
    print("metadata =", metadata_path)
    print("test_predictions =", predictions_path)
    print("status_marker =", marker_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
