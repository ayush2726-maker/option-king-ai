"""Broker-side protective/trailing stop synchronization for Option King AI.

Installed at startup by run_app.py.  The module deliberately wraps the final
runtime functions instead of editing strategy math inside app.py.

Scope:
- LIVE positions only.
- Angel SmartAPI route (`app.obj`) only; PAPER is untouched.
- Place a broker STOPLOSS_MARKET SELL after a live entry.
- Move (never loosen) that stop whenever the app's live SL trails upward.
- If a fresh broker quote is already at/below the desired SL, do not submit an
  invalid trailing modification; use the app's guarded live exit path instead.
- Before an app-driven close, cancel the resting protective stop to avoid a
  later orphaned SELL.  If the close fails and the position remains open, re-arm
  protection.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Dict, Optional, Tuple

_INSTALL_FLAG = "_okai_broker_trailing_sl_installed"
_LOCK = threading.RLock()
_EPS = 1e-9


def _log(app, message: str) -> None:
    try:
        app.gui_log(message)
    except Exception:
        pass


def _f(value: Any) -> Optional[float]:
    try:
        value = float(value)
        if math.isfinite(value):
            return value
    except Exception:
        pass
    return None


def _i(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except Exception:
        return 0


def _mode_live(pos: Dict[str, Any]) -> bool:
    return str(pos.get("mode") or "").upper() == "LIVE"


def _qty(pos: Dict[str, Any]) -> int:
    for key in ("qty", "quantity", "remaining_qty", "open_qty"):
        q = _i(pos.get(key))
        if q > 0:
            return q
    return 0


def _option(pos: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("_broker_sl_option", "option", "selected_option"):
        value = pos.get(key)
        if isinstance(value, dict) and value:
            return dict(value)
    return {}


def _extract_order_id(response: Any) -> str:
    if isinstance(response, str):
        return response.strip()
    if not isinstance(response, dict):
        return ""
    for src in (response, response.get("data") if isinstance(response.get("data"), dict) else {}):
        for key in ("orderid", "order_id", "orderId"):
            value = src.get(key)
            if value:
                return str(value).strip()
    return ""


def _angel(app):
    login = getattr(app, "angel_login", None)
    if callable(login):
        try:
            login()
        except TypeError:
            login(force=False, reason="broker protective SL")
    obj = getattr(app, "obj", None)
    if obj is None:
        raise RuntimeError("Angel broker session unavailable")
    return obj


def _fresh_ltp(app, option: Dict[str, Any]) -> Optional[float]:
    helper = getattr(app, "_okai_fresh_option_ltp", None)
    if callable(helper):
        try:
            value = _f(helper(option, "broker_protective_sl", max_age_seconds=0))
            if value is not None and value > 0:
                return value
        except TypeError:
            try:
                value = _f(helper(option, "broker_protective_sl"))
                if value is not None and value > 0:
                    return value
            except Exception:
                pass
        except Exception:
            pass

    obj = _angel(app)
    exchange = str(option.get("exchange") or option.get("exch_seg") or "").upper()
    symbol = str(option.get("tradingsymbol") or option.get("symbol") or option.get("trading_symbol") or "")
    token = str(option.get("symboltoken") or option.get("token") or "")
    if not (exchange and symbol and token):
        return None
    response = obj.ltpData(exchange, symbol, token)
    if isinstance(response, dict):
        data = response.get("data") if isinstance(response.get("data"), dict) else response
        for key in ("ltp", "LTP", "last_traded_price", "lastTradedPrice"):
            value = _f(data.get(key))
            if value is not None and value > 0:
                return value
    return None


def _stop_params(app, option: Dict[str, Any], qty: int, trigger: float) -> Dict[str, Any]:
    builder = getattr(app, "build_live_order_params", None)
    if not callable(builder):
        raise RuntimeError("build_live_order_params unavailable")
    params = dict(builder(option, "SELL", qty) or {})
    if not params:
        raise RuntimeError("Could not build broker order params")
    params["variety"] = "STOPLOSS"
    params["transactiontype"] = "SELL"
    params["ordertype"] = "STOPLOSS_MARKET"
    params["price"] = "0"
    params["triggerprice"] = f"{float(trigger):.2f}"
    params["quantity"] = str(int(qty))
    params.setdefault("duration", "DAY")
    params.setdefault("squareoff", "0")
    params.setdefault("stoploss", "0")
    return params


def _place_stop(app, pos: Dict[str, Any], option: Dict[str, Any], trigger: float, reason: str) -> str:
    qty = _qty(pos)
    if qty <= 0:
        raise RuntimeError("Protective SL qty is zero")
    params = _stop_params(app, option, qty, trigger)
    obj = _angel(app)
    if hasattr(obj, "placeOrderFullResponse"):
        response = obj.placeOrderFullResponse(params)
    elif hasattr(obj, "placeOrder"):
        response = obj.placeOrder(params)
    else:
        raise RuntimeError("Angel place-order API unavailable")
    order_id = _extract_order_id(response)
    if not order_id:
        raise RuntimeError(f"Protective SL broker order id missing: {str(response)[:180]}")
    pos["_broker_sl_order_id"] = order_id
    pos["_broker_sl_trigger"] = float(trigger)
    pos["_broker_sl_state"] = "ACTIVE"
    pos["_broker_sl_updated_at"] = time.time()
    _log(app, f"BROKER SL ARMED | order={order_id} | trigger={trigger:.2f} | qty={qty} | {reason}")
    return order_id


def _order_row(app, order_id: str) -> Dict[str, Any]:
    if not order_id:
        return {}
    try:
        response = _angel(app).orderBook()
    except Exception:
        return {}
    rows = response.get("data") if isinstance(response, dict) else None
    if not isinstance(rows, list):
        return {}
    wanted = str(order_id)
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = row.get("orderid") or row.get("order_id") or row.get("orderId")
        if value is not None and str(value) == wanted:
            return row
    return {}


def _status(row: Dict[str, Any]) -> str:
    return str(row.get("orderstatus") or row.get("status") or row.get("order_status") or "").strip().upper().replace(" ", "_")


def _is_filled(status: str) -> bool:
    return status in {"COMPLETE", "COMPLETED", "FILLED", "TRADED", "EXECUTED"}


def _is_terminal(status: str) -> bool:
    return _is_filled(status) or status in {"CANCELLED", "CANCELED", "REJECTED"}


def _cancel_stop(app, pos: Dict[str, Any], reason: str) -> Tuple[bool, str]:
    order_id = str(pos.get("_broker_sl_order_id") or "")
    if not order_id:
        return True, "NO_ORDER"
    row = _order_row(app, order_id)
    status = _status(row)
    if _is_filled(status):
        pos["_broker_sl_state"] = "FILLED"
        return False, "FILLED"
    if status in {"CANCELLED", "CANCELED"}:
        pos["_broker_sl_state"] = "CANCELLED"
        return True, status

    obj = _angel(app)
    variety = str((row or {}).get("variety") or "STOPLOSS")
    try:
        obj.cancelOrder(order_id, variety)
    except TypeError:
        obj.cancelOrder({"variety": variety, "orderid": order_id})
    time.sleep(0.15)
    after = _order_row(app, order_id)
    after_status = _status(after)
    if after_status and not (after_status in {"CANCELLED", "CANCELED"} or _is_terminal(after_status)):
        raise RuntimeError(f"Protective SL cancel not confirmed: {after_status}")
    if _is_filled(after_status):
        pos["_broker_sl_state"] = "FILLED"
        return False, "FILLED"
    pos["_broker_sl_state"] = "CANCELLED"
    _log(app, f"BROKER SL CANCELLED | order={order_id} | {reason}")
    return True, "CANCELLED"


def _modify_stop(app, pos: Dict[str, Any], option: Dict[str, Any], trigger: float, reason: str) -> str:
    order_id = str(pos.get("_broker_sl_order_id") or "")
    if not order_id:
        return _place_stop(app, pos, option, trigger, reason)

    row = _order_row(app, order_id)
    status = _status(row)
    if _is_filled(status):
        pos["_broker_sl_state"] = "FILLED"
        raise RuntimeError("Protective SL already filled")
    if status in {"CANCELLED", "CANCELED", "REJECTED"}:
        pos["_broker_sl_order_id"] = ""
        return _place_stop(app, pos, option, trigger, f"{reason}; re-arm after {status}")

    params = _stop_params(app, option, _qty(pos), trigger)
    params["orderid"] = order_id
    params["variety"] = str((row or {}).get("variety") or "STOPLOSS")
    response = _angel(app).modifyOrder(params)
    if isinstance(response, dict) and response.get("status") is False:
        raise RuntimeError(str(response.get("message") or response)[:180])

    pos["_broker_sl_trigger"] = float(trigger)
    pos["_broker_sl_state"] = "ACTIVE"
    pos["_broker_sl_updated_at"] = time.time()
    _log(app, f"BROKER SL TRAILED | order={order_id} | trigger={trigger:.2f} | {reason}")
    return order_id


def _guarded_market_exit(app, pos: Dict[str, Any], ltp: float, trigger: float, reason: str) -> bool:
    if pos.get("_broker_sl_exit_inflight"):
        return False
    pos["_broker_sl_exit_inflight"] = True
    _log(app, f"BROKER SL BREACH | fresh={ltp:.2f} <= sl={trigger:.2f} | immediate guarded exit | {reason}")
    try:
        closer = getattr(app, "close_position", None)
        if not callable(closer):
            raise RuntimeError("close_position unavailable")
        try:
            closer("BROKER_SL_STALE_FALLBACK")
        except TypeError:
            try:
                closer(reason="BROKER_SL_STALE_FALLBACK")
            except TypeError:
                closer()
        return True
    finally:
        current = getattr(app, "position", None)
        if isinstance(current, dict):
            current["_broker_sl_exit_inflight"] = False


def _sync(app, pos: Dict[str, Any], trigger: float, reason: str, allow_exit: bool = True) -> bool:
    if not isinstance(pos, dict) or not _mode_live(pos):
        return False
    trigger = _f(trigger)
    if trigger is None or trigger <= 0:
        return False
    option = _option(pos)
    if not option:
        _log(app, "BROKER SL SKIP | option metadata missing")
        return False

    with _LOCK:
        current = _f(pos.get("_broker_sl_trigger"))
        if current is not None and trigger <= current + _EPS:
            return True

        fresh = _fresh_ltp(app, option)
        if allow_exit and fresh is not None and fresh <= trigger + _EPS:
            return _guarded_market_exit(app, pos, fresh, trigger, reason)

        last_error = None
        for attempt in range(1, 4):
            try:
                _modify_stop(app, pos, option, trigger, reason)
                return True
            except Exception as exc:
                last_error = exc
                _log(app, f"BROKER SL SYNC RETRY {attempt}/3 | {str(exc)[:180]}")
                if attempt < 3:
                    time.sleep(0.25 * attempt)

        pos["_broker_sl_state"] = "ERROR"
        pos["_broker_sl_last_error"] = str(last_error)[:220]
        _log(app, f"BROKER SL SYNC FAILED | {str(last_error)[:220]}")
        if allow_exit:
            try:
                fresh = _fresh_ltp(app, option)
                if fresh is not None and fresh <= trigger + _EPS:
                    return _guarded_market_exit(app, pos, fresh, trigger, "sync failure")
            except Exception:
                pass
        return False


def install(app) -> Tuple[bool, str]:
    """Install broker-side SL hooks once. Returns (ok, reason)."""
    if getattr(app, _INSTALL_FLAG, False):
        return True, "already installed"

    base_open = getattr(app, "_open_position_after_entry", None)
    base_trail = getattr(app, "update_trailing_sl", None)
    base_close = getattr(app, "close_position", None)
    if not all(callable(x) for x in (base_open, base_trail, base_close)):
        return False, "required runtime functions missing"

    def open_position_after_entry(*args, **kwargs):
        pos = base_open(*args, **kwargs)
        try:
            option = kwargs.get("option")
            mode = kwargs.get("mode")
            if option is None and len(args) >= 4:
                option = args[3]
            if mode is None and len(args) >= 6:
                mode = args[5]
            target = pos if isinstance(pos, dict) else getattr(app, "position", None)
            if isinstance(target, dict):
                if isinstance(option, dict) and option:
                    target["_broker_sl_option"] = dict(option)
                if mode and not target.get("mode"):
                    target["mode"] = str(mode)
                sl = _f(target.get("sl"))
                if _mode_live(target) and sl and sl > 0:
                    _sync(app, target, sl, "entry protection", allow_exit=True)
        except Exception as exc:
            _log(app, f"BROKER SL ENTRY PROTECTION ERROR | {str(exc)[:220]}")
        return pos

    def update_trailing_sl(*args, **kwargs):
        result = base_trail(*args, **kwargs)
        try:
            pos = getattr(app, "position", None)
            if isinstance(pos, dict) and _mode_live(pos):
                sl = _f(pos.get("sl"))
                if sl and sl > 0:
                    _sync(app, pos, sl, "app trail", allow_exit=True)
        except Exception as exc:
            _log(app, f"BROKER SL TRAIL HOOK ERROR | {str(exc)[:220]}")
        return result

    def close_position(*args, **kwargs):
        pos = getattr(app, "position", None)
        cancelled = False
        old_trigger = None
        if isinstance(pos, dict) and _mode_live(pos) and pos.get("_broker_sl_order_id"):
            with _LOCK:
                old_trigger = _f(pos.get("_broker_sl_trigger") or pos.get("sl"))
                try:
                    cancelled, status = _cancel_stop(app, pos, "app close")
                    if status == "FILLED":
                        pos["_broker_sl_filled_before_app_close"] = True
                        _log(app, "APP CLOSE SUPPRESSED | broker protective SL already filled")
                        return False
                except Exception as exc:
                    _log(app, f"APP CLOSE BLOCKED | protective SL cancel failed | {str(exc)[:200]}")
                    return False

        try:
            result = base_close(*args, **kwargs)
        except Exception:
            current = getattr(app, "position", None)
            if cancelled and isinstance(current, dict) and _mode_live(current) and old_trigger:
                current["_broker_sl_order_id"] = ""
                try:
                    _sync(app, current, old_trigger, "re-arm after close exception", allow_exit=False)
                except Exception:
                    pass
            raise

        current = getattr(app, "position", None)
        if cancelled and isinstance(current, dict) and _mode_live(current):
            current["_broker_sl_order_id"] = ""
            trigger = _f(current.get("sl")) or old_trigger
            if trigger:
                try:
                    _sync(app, current, trigger, "re-arm after incomplete close", allow_exit=False)
                except Exception:
                    pass
        return result

    app._open_position_after_entry = open_position_after_entry
    app.update_trailing_sl = update_trailing_sl
    app.close_position = close_position
    setattr(app, _INSTALL_FLAG, True)
    _log(app, "Broker-side protective/trailing SL sync installed")
    return True, "broker-side protective/trailing SL sync installed"
