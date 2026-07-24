"""Non-blocking Railway shared-AI shadow integration for the personal bot.

This wrapper only observes status data. It never changes signals, entries,
exits, quantities, paper trades, live orders, cooldowns or risk decisions.
"""
from __future__ import annotations

import datetime as _dt
import threading
import time
from typing import Any, Dict, Iterable, Mapping

from ai_shadow_outcome_monitor import ShadowOutcomeMonitor
from railway_ai_client import get_personal_ai_decision

_REFRESH_SECONDS = 15.0
_LOCK = threading.Lock()
_INFLIGHT = False
_LAST_REQUEST_MONOTONIC = 0.0
_LAST_LOG_KEY = ""
_MONITOR = ShadowOutcomeMonitor()
_CACHE: Dict[str, Any] = {
    "success": False,
    "model_version": "shadow-pending",
    "decision": "NO_TRADE",
    "confidence": 0,
    "probabilities": {"CE": 0, "PE": 0, "NO_TRADE": 100},
    "risk_allowed": False,
    "reasons": ["SHADOW_PENDING"],
    "decision_location": "PERSONAL_SHADOW_CACHE",
    "order_execution": False,
    "mode": "SHADOW_ONLY",
    "updated_at": None,
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _boolean(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "open", "connected", "running", "active"}:
        return True
    if text in {"0", "false", "no", "off", "closed", "disconnected", "stopped", "inactive"}:
        return False
    return bool(default)


def _first(mapping: Mapping[str, Any], names: Iterable[str], default: Any = None) -> Any:
    for name in names:
        try:
            value = mapping.get(name)
        except Exception:
            continue
        if value is not None and value != "":
            return value
    return default


def _direction(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"CE", "CALL", "CALL_BUY", "BULL", "BULLISH", "UP", "LONG_CE"}:
        return "CE"
    if text in {"PE", "PUT", "PUT_BUY", "BEAR", "BEARISH", "DOWN", "SHORT", "LONG_PE"}:
        return "PE"
    return "WAIT"


def _safe_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _ist_market_open_fallback() -> bool:
    now = _dt.datetime.utcnow() + _dt.timedelta(hours=5, minutes=30)
    if now.weekday() >= 5:
        return False
    minute = now.hour * 60 + now.minute
    return (9 * 60 + 15) <= minute <= (15 * 60 + 30)


def _market_open(module_globals: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    explicit = _first(payload, ("market_open", "is_market_open"), None)
    if explicit is not None:
        return _boolean(explicit, False)
    status_text = str(_first(payload, ("market_status", "session_status"), "")).upper()
    if "CLOSED" in status_text or "HOLIDAY" in status_text:
        return False
    if "OPEN" in status_text:
        return True
    return _ist_market_open_fallback()


def _indicator_snapshot(module_globals: Dict[str, Any], price: float) -> Dict[str, Any]:
    builder = module_globals.get("weighted_indicator_snapshot")
    if not callable(builder):
        return {}
    for name in ("df", "nifty_df", "market_df", "candles_df", "last_df"):
        frame = module_globals.get(name)
        if frame is None:
            continue
        try:
            snapshot = builder(frame, price=price)
            if isinstance(snapshot, dict):
                return snapshot
        except Exception:
            continue
    return {}


def build_shadow_snapshot(module_globals: Dict[str, Any], payload: Mapping[str, Any]) -> Dict[str, Any]:
    payload_dict = dict(payload or {})
    suggestion = _safe_mapping(module_globals.get("last_trade_suggestion"))
    config = _safe_mapping(module_globals.get("config"))
    price = _number(
        _first(
            payload_dict,
            ("price", "nifty", "nifty_price", "spot_price", "last_price", "ltp", "close"),
            module_globals.get("last_nifty_price", 0),
        ),
        0,
    )
    raw_signal = _first(
        payload_dict,
        ("signal", "last_signal", "decision", "side"),
        _first(suggestion, ("signal", "decision", "side"), module_globals.get("last_signal")),
    )
    signal = _direction(raw_signal)
    score = _number(
        _first(
            payload_dict,
            ("strategy_score", "score", "last_score"),
            _first(suggestion, ("strategy_score", "score"), module_globals.get("last_score", 0)),
        ),
        0,
    )
    min_score = _number(
        _first(
            payload_dict,
            ("min_strategy_score", "min_score", "entry_score_threshold"),
            _first(config, ("min_strategy_score", "min_score", "weighted_min_entry_score"), 82),
        ),
        82,
    )
    indicators = _indicator_snapshot(module_globals, price)
    volume = _number(_first(indicators, ("volume",), _first(payload_dict, ("volume",), 0)), 0)
    average_volume = _number(
        _first(indicators, ("avg_volume", "average_volume"), _first(payload_dict, ("avg_volume",), 0)),
        0,
    )
    volume_ratio = _number(_first(payload_dict, ("volume_ratio",), None), -1)
    if volume_ratio < 0:
        volume_ratio = (volume / average_volume) if average_volume > 0 else 0
    position = payload_dict.get("position")
    if position in (None, {}, [], ""):
        position = module_globals.get("position")
    mtf_direction = _direction(
        _first(
            payload_dict,
            ("mtf_direction", "mtf_trend"),
            _first(suggestion, ("mtf_direction", "mtf_trend"), "WAIT"),
        )
    )
    mtf_confirmed_raw = _first(payload_dict, ("mtf_confirmed",), None)
    if mtf_confirmed_raw is None:
        mtf_confirmed = signal in {"CE", "PE"} and mtf_direction == signal
    else:
        mtf_confirmed = _boolean(mtf_confirmed_raw, False)
    trade_allowed_raw = _first(payload_dict, ("trade_allowed", "entry_allowed"), None)
    if trade_allowed_raw is None:
        trade_allowed = signal in {"CE", "PE"}
    else:
        trade_allowed = _boolean(trade_allowed_raw, False)
    feed_connected = _boolean(
        _first(payload_dict, ("feed_connected", "data_feed_connected", "websocket_connected"), None),
        price > 0,
    )
    return {
        "source": "PERSONAL_OPTION_KING_SHADOW",
        "symbol": str(_first(payload_dict, ("symbol", "underlying"), "NIFTY")),
        "price": price,
        "signal": signal,
        "signal_direction": signal,
        "strategy_score": score,
        "min_strategy_score": min_score,
        "server_trade_allowed": trade_allowed,
        "ema_fast": _number(
            _first(payload_dict, ("ema_fast", "ema20", "ema9"), _first(indicators, ("ema9", "ema_fast"), 0)),
            0,
        ),
        "ema_slow": _number(
            _first(payload_dict, ("ema_slow", "ema50", "ema21"), _first(indicators, ("ema21", "ema_slow"), 0)),
            0,
        ),
        "vwap": _number(_first(payload_dict, ("vwap",), _first(indicators, ("vwap",), 0)), 0),
        "supertrend_direction": _first(
            payload_dict,
            ("supertrend_direction", "supertrend_dir", "supertrend"),
            _first(indicators, ("supertrend", "supertrend_direction"), _first(suggestion, ("supertrend",), "")),
        ),
        "structure_direction": _first(
            payload_dict,
            ("structure_direction", "market_structure"),
            _first(suggestion, ("structure_direction", "market_structure"), ""),
        ),
        "mtf_direction": mtf_direction,
        "mtf_confirmed": mtf_confirmed,
        "adx": _number(
            _first(payload_dict, ("adx", "adx14"), _first(indicators, ("adx14", "adx"), 0)),
            0,
        ),
        "rsi": _number(
            _first(payload_dict, ("rsi", "rsi14"), _first(indicators, ("rsi", "rsi14"), 50)),
            50,
        ),
        "atr": _number(_first(payload_dict, ("atr",), _first(indicators, ("atr",), 0)), 0),
        "atr_percent": _number(
            _first(payload_dict, ("atr_percent",), _first(indicators, ("atr_percent",), 0)),
            0,
        ),
        "volume_ratio": volume_ratio,
        "spread_percent": _number(_first(payload_dict, ("spread_percent",), 0), 0),
        "market_regime": str(
            _first(payload_dict, ("market_regime", "regime"), _first(suggestion, ("market_regime", "regime"), ""))
        ),
        "feed_connected": feed_connected,
        "feed_age_ms": _number(
            _first(payload_dict, ("feed_age_ms", "data_age_ms", "price_age_ms"), None),
            0 if feed_connected and price > 0 else 999999,
        ),
        "market_open": _market_open(module_globals, payload_dict),
        "daily_loss_percent": _number(_first(payload_dict, ("daily_loss_percent",), 0), 0),
        "consecutive_losses": int(_number(_first(payload_dict, ("consecutive_losses",), 0), 0)),
        "has_open_position": _boolean(
            _first(payload_dict, ("has_open_position", "position_open"), None),
            bool(position),
        ),
    }


def _slim_result(result: Any) -> Dict[str, Any]:
    result = result if isinstance(result, dict) else {}
    decision = str(result.get("decision") or "NO_TRADE").upper()
    if decision not in {"CE", "PE", "NO_TRADE"}:
        decision = "NO_TRADE"
    probabilities = (
        result.get("probabilities")
        if isinstance(result.get("probabilities"), dict)
        else {"CE": 0, "PE": 0, "NO_TRADE": 100}
    )
    reasons = result.get("reasons")
    if not isinstance(reasons, list):
        reasons = [str(reasons)] if reasons else []
    return {
        "success": bool(result.get("success")),
        "model_version": str(result.get("model_version") or "railway-unavailable"),
        "decision": decision,
        "confidence": int(_number(result.get("confidence"), 0)),
        "probabilities": {
            "CE": int(_number(probabilities.get("CE"), 0)),
            "PE": int(_number(probabilities.get("PE"), 0)),
            "NO_TRADE": int(_number(probabilities.get("NO_TRADE"), 100)),
        },
        "risk_allowed": bool(result.get("risk_allowed")),
        "reasons": [str(item)[:120] for item in reasons[:8]],
        "decision_location": str(result.get("decision_location") or "RAILWAY_SHARED_AI"),
        "order_execution": False,
        "mode": "SHADOW_ONLY",
        "updated_at": _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }


def _log(module_globals: Dict[str, Any], message: str) -> None:
    logger = module_globals.get("gui_log") or module_globals.get("_okai_fix_log")
    try:
        if callable(logger):
            logger(message)
        else:
            print(message)
    except Exception:
        pass


def _worker(module_globals: Dict[str, Any], snapshot: Dict[str, Any]) -> None:
    global _INFLIGHT, _CACHE, _LAST_LOG_KEY
    try:
        result = _slim_result(get_personal_ai_decision(snapshot))
    except Exception as exc:
        result = _slim_result(
            {
                "success": False,
                "model_version": "railway-unavailable",
                "decision": "NO_TRADE",
                "confidence": 100,
                "probabilities": {"CE": 0, "PE": 0, "NO_TRADE": 100},
                "risk_allowed": False,
                "reasons": ["SHADOW_EXCEPTION_%s" % type(exc).__name__],
            }
        )
    with _LOCK:
        _CACHE = result
        _INFLIGHT = False
    try:
        _MONITOR.register_decision(snapshot, result)
    except Exception:
        pass
    log_key = "%s|%s|%s" % (
        result.get("decision"),
        result.get("confidence"),
        ",".join(result.get("reasons") or []),
    )
    if log_key != _LAST_LOG_KEY:
        _LAST_LOG_KEY = log_key
        _log(
            module_globals,
            "RAILWAY AI SHADOW | %s %s%% | %s | monitor only, trade blocking OFF"
            % (
                result.get("decision"),
                result.get("confidence"),
                ", ".join(result.get("reasons") or []) or "OK",
            ),
        )


def _schedule(module_globals: Dict[str, Any], payload: Dict[str, Any]) -> None:
    global _INFLIGHT, _LAST_REQUEST_MONOTONIC
    try:
        _MONITOR.observe(payload)
    except Exception:
        pass
    now = time.monotonic()
    with _LOCK:
        if _INFLIGHT or (now - _LAST_REQUEST_MONOTONIC) < _REFRESH_SECONDS:
            return
        _INFLIGHT = True
        _LAST_REQUEST_MONOTONIC = now
    try:
        snapshot = build_shadow_snapshot(module_globals, payload)
        thread = threading.Thread(
            target=_worker,
            args=(module_globals, snapshot),
            name="okai-railway-ai-shadow",
            daemon=True,
        )
        thread.start()
    except Exception:
        with _LOCK:
            _INFLIGHT = False


def current_shadow_status() -> Dict[str, Any]:
    with _LOCK:
        return dict(_CACHE)


def current_shadow_monitor() -> Dict[str, Any]:
    try:
        return _MONITOR.status()
    except Exception:
        return {
            "mode": "MONITOR_ONLY",
            "trade_blocking": False,
            "order_execution": False,
            "error": "MONITOR_STATUS_UNAVAILABLE",
        }


def install(module_globals: Dict[str, Any]) -> bool:
    """Wrap status_payload without touching any trading decision path."""
    base = module_globals.get("status_payload")
    if not callable(base):
        return False
    if getattr(base, "_okai_railway_shadow_wrapped", False):
        return True

    def status_payload_wrapper(*args: Any, **kwargs: Any) -> Any:
        data = base(*args, **kwargs)
        if not isinstance(data, dict):
            return data
        _schedule(module_globals, data)
        data["railway_ai_shadow"] = current_shadow_status()
        data["railway_ai_monitor"] = current_shadow_monitor()
        data["railway_ai_mode"] = "SHADOW_MONITOR_ONLY"
        data["railway_ai_trade_blocking"] = False
        data["railway_ai_order_execution"] = False
        return data

    status_payload_wrapper.__name__ = getattr(base, "__name__", "status_payload")
    status_payload_wrapper.__doc__ = getattr(base, "__doc__", None)
    status_payload_wrapper._okai_railway_shadow_wrapped = True
    status_payload_wrapper._okai_railway_shadow_base = base
    module_globals["status_payload"] = status_payload_wrapper
    module_globals["railway_ai_shadow_status"] = current_shadow_status
    module_globals["railway_ai_shadow_monitor"] = current_shadow_monitor
    _log(
        module_globals,
        "RAILWAY AI SHADOW MONITOR V1 active | decisions logged | trade blocking OFF | order execution OFF",
    )
    return True
