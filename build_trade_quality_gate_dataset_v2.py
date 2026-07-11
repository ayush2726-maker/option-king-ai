"""Strict wrapper for build_trade_quality_gate_dataset.py.

The V1 builder used substring matching for words such as ``net`` and ``exit``.
That incorrectly rejected valid pre-entry history features including
``previous_trade_net`` and ``minutes_since_previous_exit``. This wrapper uses
an exact reviewed feature allow-list, then runs the unchanged V1 builder.

Safety: research only; does not import app.py or touch orders.
"""

from __future__ import annotations

import build_trade_quality_gate_dataset as v1

EXPECTED_FEATURES = {
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
}

EXACT_FORBIDDEN = {
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
    "label_win",
    "target_net",
}

FORBIDDEN_PREFIXES = (
    "future_",
    "target_",
    "label_",
    "realized_",
    "realised_",
    "post_entry_",
)


def main() -> int:
    actual = set(v1.FEATURES)

    missing = sorted(EXPECTED_FEATURES - actual)
    unexpected = sorted(actual - EXPECTED_FEATURES)
    explicitly_forbidden = sorted(actual & EXACT_FORBIDDEN)
    prefixed_forbidden = sorted(
        feature
        for feature in actual
        if feature.startswith(FORBIDDEN_PREFIXES)
    )

    problems = {
        "missing_reviewed_features": missing,
        "unexpected_unreviewed_features": unexpected,
        "exact_forbidden_features": explicitly_forbidden,
        "forbidden_prefix_features": prefixed_forbidden,
    }
    problems = {key: value for key, value in problems.items() if value}

    if problems:
        raise RuntimeError(f"Strict leakage audit failed: {problems}")

    # V1's substring guard is replaced only after the strict allow-list audit.
    v1.FORBIDDEN_FEATURE_WORDS = ("__STRICT_V2_AUDIT_ALREADY_PASSED__",)

    print("strict_feature_allowlist = PASS")
    print("reviewed_features =", len(actual))
    print("pre_entry_history_features = ALLOWED")
    return v1.main()


if __name__ == "__main__":
    raise SystemExit(main())
