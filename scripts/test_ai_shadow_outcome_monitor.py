"""Smoke tests for the non-blocking AI shadow outcome monitor."""
from __future__ import annotations

import datetime as dt
import tempfile

from ai_shadow_outcome_monitor import ShadowOutcomeMonitor


def force_age(record, minutes):
    record["created_at"] = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes)
    ).isoformat().replace("+00:00", "Z")


def main():
    monitor = ShadowOutcomeMonitor(tempfile.mkdtemp(prefix="okai-ai-shadow-test-"))

    # Strategy wanted CE, AI said NO_TRADE, and market fell: AI block would help.
    assert monitor.register_decision(
        {
            "symbol": "NIFTY",
            "price": 25000,
            "signal": "CE",
            "signal_direction": "CE",
            "strategy_score": 88,
            "min_strategy_score": 82,
            "server_trade_allowed": True,
            "market_open": True,
        },
        {
            "success": True,
            "decision": "NO_TRADE",
            "confidence": 90,
            "probabilities": {"CE": 5, "PE": 5, "NO_TRADE": 90},
            "reasons": ["DIRECTION_CONFLICT"],
            "model_version": "test",
        },
    )
    force_age(monitor.pending[0], 16)
    monitor.observe({"price": 24970})
    summary = monitor.summary()
    assert summary["trade_blocking"] is False
    assert summary["order_execution"] is False
    assert summary["ai_block_would_help_count_15m"] == 1
    assert summary["estimated_ai_benefit_spot_points_15m"] == 30.0

    # Directional AI CE prediction and rising market: one shadow win.
    monitor.last_record_key = ""
    monitor.last_recorded_at = None
    assert monitor.register_decision(
        {
            "symbol": "NIFTY",
            "price": 25100,
            "signal": "CE",
            "signal_direction": "CE",
            "strategy_score": 90,
            "min_strategy_score": 82,
            "server_trade_allowed": True,
            "market_open": True,
        },
        {
            "success": True,
            "decision": "CE",
            "confidence": 82,
            "probabilities": {"CE": 82, "PE": 8, "NO_TRADE": 10},
            "reasons": [],
            "model_version": "test",
        },
    )
    force_age(monitor.pending[-1], 16)
    monitor.observe({"price": 25125})
    summary = monitor.summary()
    assert summary["wins_15m"] == 1
    assert summary["directional_hit_rate_percent_15m"] == 100.0

    print("PASS OKAI-AI-SHADOW-MONITOR-V1")


if __name__ == "__main__":
    main()
