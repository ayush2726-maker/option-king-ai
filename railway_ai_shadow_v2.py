"""Railway AI shadow V2 for the personal Option King server.

Safety guarantees:
- Wraps status output only.
- Runs Railway calls in daemon/background threads.
- Never changes local signal, entry, exit, quantity, paper trade, or live order.
- Exposes the cached result in both full and compact status payloads.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict

import railway_ai_shadow as _base


_BACKGROUND_LOCK = threading.Lock()
_BACKGROUND_STARTED = False


def _log(module_globals: Dict[str, Any], message: str) -> None:
    logger = module_globals.get("gui_log") or module_globals.get("_okai_fix_log")
    try:
        if callable(logger):
            logger(message)
        else:
            print(message)
    except Exception:
        pass


def _decorate(data: Any, module_globals: Dict[str, Any]) -> Any:
    if not isinstance(data, dict):
        return data
    try:
        _base._schedule(module_globals, data)
    except Exception:
        pass
    data["railway_ai_shadow"] = _base.current_shadow_status()
    data["railway_ai_mode"] = "SHADOW_ONLY"
    data["railway_ai_order_execution"] = False
    return data


def _wrap(module_globals: Dict[str, Any], function_name: str) -> bool:
    current = module_globals.get(function_name)
    if not callable(current):
        return False
    if getattr(current, "_okai_railway_shadow_v2_wrapped", False):
        return True

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return _decorate(current(*args, **kwargs), module_globals)

    wrapper.__name__ = getattr(current, "__name__", function_name)
    wrapper.__doc__ = getattr(current, "__doc__", None)
    wrapper._okai_railway_shadow_v2_wrapped = True
    wrapper._okai_railway_shadow_v2_base = current
    module_globals[function_name] = wrapper
    return True


def _background_loop(module_globals: Dict[str, Any]) -> None:
    # Trigger immediately, then keep the shadow cache fresh even when no mobile
    # client is polling /status. _base._schedule has its own 15-second limiter.
    while True:
        try:
            _base._schedule(module_globals, {})
        except Exception as exc:
            _log(
                module_globals,
                "RAILWAY AI SHADOW background skipped: %s" % type(exc).__name__,
            )
        time.sleep(5.0)


def _start_background(module_globals: Dict[str, Any]) -> None:
    global _BACKGROUND_STARTED
    with _BACKGROUND_LOCK:
        if _BACKGROUND_STARTED:
            return
        _BACKGROUND_STARTED = True

    thread = threading.Thread(
        target=_background_loop,
        args=(module_globals,),
        name="okai-railway-ai-shadow-refresh",
        daemon=True,
    )
    thread.start()


def install(module_globals: Dict[str, Any]) -> bool:
    full_ok = _wrap(module_globals, "status_payload")
    compact_ok = _wrap(module_globals, "compact_status_payload")

    module_globals["railway_ai_shadow_status"] = _base.current_shadow_status
    _start_background(module_globals)

    _log(
        module_globals,
        "RAILWAY AI SHADOW V2 active | full+compact status | background refresh | order execution OFF",
    )
    return bool(full_ok or compact_ok)
