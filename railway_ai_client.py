"""Client for the shared Option King AI service running on Railway.

Safe design:
- Sends market features only.
- Never sends broker credentials, tokens, passwords, TOTP, or order details.
- Fails closed to NO_TRADE when Railway is unavailable or the response is invalid.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_AI_URL = (
    "https://option-king-saas-production.up.railway.app/ai/predict"
)


def _load_personal_config() -> Dict[str, Any]:
    candidates = []
    explicit = os.getenv("OKAI_CONFIG_PATH", "").strip()
    if explicit:
        candidates.append(explicit)
    candidates.extend([
        os.path.join(os.getcwd(), "config.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
    ])

    seen = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def _ai_settings():
    config = _load_personal_config()
    enabled = config.get("railway_ai_enabled", True)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() not in {"0", "false", "no", "off"}

    api_key = (
        os.getenv("OKAI_AI_API_KEY", "").strip()
        or str(config.get("railway_ai_api_key") or config.get("ai_api_key") or "").strip()
    )
    url = (
        os.getenv("OKAI_AI_URL", "").strip()
        or str(config.get("railway_ai_url") or "").strip()
        or DEFAULT_AI_URL
    )
    return bool(enabled), api_key, url


def build_personal_ai_snapshot(status: Dict[str, Any]) -> Dict[str, Any]:
    """Map personal bot status/strategy fields to the shared AI contract."""
    status = dict(status or {})
    signal = status.get("signal") or status.get("side") or status.get("decision") or "WAIT"
    updated_at = status.get("updated_at") or status.get("timestamp")

    feed_age_ms = status.get("feed_age_ms")
    if feed_age_ms is None:
        # Replace with real data age whenever the personal bot exposes it.
        feed_age_ms = 0 if status.get("feed_connected", True) else 999999

    return {
        "source": "PERSONAL_OPTION_KING",
        "symbol": status.get("symbol") or status.get("underlying") or "NIFTY",
        "price": status.get("price") or status.get("ltp") or status.get("close") or 0,
        "signal": signal,
        "signal_direction": signal,
        "strategy_score": status.get("strategy_score", status.get("score", 0)),
        "min_strategy_score": status.get("min_strategy_score", status.get("min_score", 82)),
        "server_trade_allowed": status.get("trade_allowed", False),
        "ema_fast": status.get("ema_fast", status.get("ema20", status.get("ema9"))),
        "ema_slow": status.get("ema_slow", status.get("ema50", status.get("ema21"))),
        "vwap": status.get("vwap"),
        "supertrend_direction": status.get(
            "supertrend_direction",
            status.get("supertrend_dir", status.get("supertrend")),
        ),
        "structure_direction": status.get("structure_direction", status.get("market_structure")),
        "mtf_direction": status.get("mtf_direction", status.get("mtf_trend")),
        "mtf_confirmed": status.get("mtf_confirmed", False),
        "adx": status.get("adx", 0),
        "rsi": status.get("rsi", 50),
        "atr": status.get("atr", 0),
        "atr_percent": status.get("atr_percent"),
        "volume_ratio": status.get("volume_ratio", 0),
        "spread_percent": status.get("spread_percent", 0),
        "market_regime": status.get("market_regime", status.get("regime", "")),
        "feed_connected": status.get("feed_connected", True),
        "feed_age_ms": feed_age_ms,
        "market_open": status.get("market_open", True),
        "daily_loss_percent": status.get("daily_loss_percent", 0),
        "consecutive_losses": status.get("consecutive_losses", 0),
        "has_open_position": status.get("has_open_position", False),
        "client_updated_at": updated_at,
    }


def _blocked(reason: str) -> Dict[str, Any]:
    return {
        "success": False,
        "model_version": "railway-unavailable",
        "decision": "NO_TRADE",
        "confidence": 100,
        "probabilities": {"CE": 0, "PE": 0, "NO_TRADE": 100},
        "risk_allowed": False,
        "reasons": [reason],
        "order_execution": False,
    }


def predict_with_railway(
    snapshot: Dict[str, Any],
    timeout_seconds: float = 6.0,
) -> Dict[str, Any]:
    """Call Railway shared AI. Any failure returns a safe NO_TRADE response."""
    enabled, api_key, url = _ai_settings()

    if not enabled:
        return _blocked("AI_DISABLED")
    if not api_key:
        return _blocked("AI_API_KEY_MISSING")

    body = json.dumps(dict(snapshot or {}), separators=(",", ":")).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-AI-Key": api_key,
            "User-Agent": "OptionKingPersonal/1.0",
        },
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return _blocked("AI_HTTP_%s" % exc.code)
    except (URLError, TimeoutError, OSError):
        return _blocked("AI_SERVER_UNREACHABLE")
    except ValueError:
        return _blocked("AI_INVALID_RESPONSE")

    if not isinstance(data, dict):
        return _blocked("AI_INVALID_RESPONSE")
    if data.get("decision") not in {"CE", "PE", "NO_TRADE"}:
        return _blocked("AI_INVALID_DECISION")

    data.setdefault("order_execution", False)
    return data


def get_personal_ai_decision(status: Dict[str, Any]) -> Dict[str, Any]:
    return predict_with_railway(build_personal_ai_snapshot(status))
