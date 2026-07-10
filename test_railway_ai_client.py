import json

from railway_ai_client import get_personal_ai_decision


snapshot = {
    "symbol": "NIFTY",
    "price": 24520,
    "signal": "CE",
    "score": 88,
    "min_score": 82,
    "trade_allowed": True,
    "ema20": 24505,
    "ema50": 24472,
    "vwap": 24490,
    "supertrend_direction": "UP",
    "structure_direction": "UP",
    "mtf_direction": "UP",
    "mtf_confirmed": True,
    "adx": 31,
    "rsi": 61,
    "atr_percent": 0.42,
    "volume_ratio": 1.45,
    "spread_percent": 0.18,
    "feed_connected": True,
    "feed_age_ms": 500,
    "market_open": True,
    "daily_loss_percent": 0,
    "consecutive_losses": 0,
    "has_open_position": False,
}

result = get_personal_ai_decision(snapshot)
print(json.dumps(result, indent=2))

if result.get("decision") != "CE":
    raise SystemExit("Railway AI test failed: expected CE")

print("\nRAILWAY AI CLIENT PASS")
