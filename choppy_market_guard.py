"""Option King AI independent choppy/sideways entry guard.

This guard wraps the existing weighted-quality gate without changing the
existing strategy, expiry rules, Hero Zero, SL/trailing, or execution code.

Rules:
- 4 independent chop signals: low ADX, EMA9/EMA21 compression,
  VWAP chop/flatness, ATR compression.
- 3/4 or 4/4 => hard block.
- After a hard chop clears, require two same-direction closes plus a fresh
  two-candle swing break and an extra +5 quality points before re-entry.
- Fail open when candle/indicator data is insufficient so stale/missing data
  does not create a permanent false block.
"""

from __future__ import annotations

import math


CHOP_ADX_MAX = 18.0
EMA_COMPRESSION_PCT = 0.20
VWAP_FLAT_PCT = 0.05
VWAP_CROSS_MIN = 3
ATR_COMPRESSION_RATIO = 0.80
RECOVERY_SCORE_BONUS = 5.0

# Kept per market/signal key. This is only a recovery latch, not trade state.
_RECOVERY_LATCH = {}


def _f(v, default=None):
    try:
        x = float(v)
        if math.isfinite(x):
            return x
    except Exception:
        pass
    return default


def _col(df, *names):
    if df is None:
        return None
    for name in names:
        try:
            if name in df.columns:
                return df[name].astype(float)
        except Exception:
            pass
    return None


def _ema(series, span):
    try:
        return series.ewm(span=span, adjust=False).mean()
    except Exception:
        return None


def _true_range(df):
    high = _col(df, "high", "High")
    low = _col(df, "low", "Low")
    close = _col(df, "close", "Close")
    if high is None or low is None or close is None:
        return None
    try:
        prev_close = close.shift(1)
        a = high - low
        b = (high - prev_close).abs()
        c = (low - prev_close).abs()
        import pandas as pd
        return pd.concat([a, b, c], axis=1).max(axis=1)
    except Exception:
        return None


def _adx(df, period=14):
    """Wilder-style ADX computed from candles when no usable ADX column exists."""
    direct = _col(df, "ADX", "adx", "Adx")
    if direct is not None:
        try:
            val = _f(direct.iloc[-1])
            if val is not None:
                return val
        except Exception:
            pass

    high = _col(df, "high", "High")
    low = _col(df, "low", "Low")
    close = _col(df, "close", "Close")
    if high is None or low is None or close is None or len(close) < period + 3:
        return None
    try:
        up = high.diff()
        down = -low.diff()
        plus_dm = up.where((up > down) & (up > 0), 0.0)
        minus_dm = down.where((down > up) & (down > 0), 0.0)
        tr = _true_range(df)
        alpha = 1.0 / period
        atr = tr.ewm(alpha=alpha, adjust=False).mean()
        plus_di = 100.0 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, float("nan"))
        minus_di = 100.0 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, float("nan"))
        dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float("nan"))
        return _f(dx.ewm(alpha=alpha, adjust=False).mean().iloc[-1])
    except Exception:
        return None


def _ema_compressed(df):
    close = _col(df, "close", "Close")
    if close is None or len(close) < 9:
        return None, None
    e9 = _col(df, "EMA9", "ema9", "EMA_9")
    e21 = _col(df, "EMA21", "ema21", "EMA_21")
    if e9 is None:
        e9 = _ema(close, 9)
    if e21 is None:
        e21 = _ema(close, 21)
    try:
        a, b, px = _f(e9.iloc[-1]), _f(e21.iloc[-1]), _f(close.iloc[-1])
        if None in (a, b, px) or px <= 0:
            return None, None
        sep = abs(a - b) / px * 100.0
        return sep <= EMA_COMPRESSION_PCT, sep
    except Exception:
        return None, None


def _vwap_chop(df):
    close = _col(df, "close", "Close")
    vwap = _col(df, "VWAP", "vwap", "Vwap")
    if close is None or vwap is None or len(close) < 6:
        return None, None
    try:
        c = close.tail(6).reset_index(drop=True)
        v = vwap.tail(6).reset_index(drop=True)
        signs = []
        for i in range(len(c)):
            d = _f(c.iloc[i] - v.iloc[i], 0.0)
            signs.append(1 if d > 0 else -1 if d < 0 else 0)
        crosses = 0
        prev = 0
        for s in signs:
            if s == 0:
                continue
            if prev and s != prev:
                crosses += 1
            prev = s

        v0, v1 = _f(v.iloc[0]), _f(v.iloc[-1])
        slope_pct = None
        flat = False
        if v0 not in (None, 0) and v1 is not None:
            slope_pct = abs(v1 - v0) / abs(v0) * 100.0
            flat = slope_pct <= VWAP_FLAT_PCT
        return (crosses >= VWAP_CROSS_MIN) or flat, {"crosses": crosses, "slope_pct": slope_pct}
    except Exception:
        return None, None


def _atr_compressed(df):
    tr = _true_range(df)
    if tr is None or len(tr) < 20:
        return None, None
    try:
        atr14 = tr.rolling(14, min_periods=10).mean()
        current = _f(atr14.iloc[-1])
        baseline = _f(atr14.tail(20).mean())
        if current is None or baseline in (None, 0):
            return None, None
        ratio = current / baseline
        return ratio <= ATR_COMPRESSION_RATIO, ratio
    except Exception:
        return None, None


def assess_chop(df):
    adx = _adx(df)
    ema_flag, ema_sep = _ema_compressed(df)
    vwap_flag, vwap_meta = _vwap_chop(df)
    atr_flag, atr_ratio = _atr_compressed(df)

    raw = {
        "adx_low": (adx is not None and adx < CHOP_ADX_MAX),
        "ema_compressed": ema_flag,
        "vwap_chop": vwap_flag,
        "atr_compressed": atr_flag,
    }
    available = {k: v for k, v in raw.items() if v is not None}
    hits = sum(1 for v in available.values() if v)
    hard_block = len(available) >= 3 and hits >= 3
    return {
        "hard_block": hard_block,
        "hits": hits,
        "available": len(available),
        "flags": raw,
        "adx": adx,
        "ema_sep_pct": ema_sep,
        "vwap": vwap_meta,
        "atr_ratio": atr_ratio,
    }


def _two_candle_recovery_ok(df, signal):
    close = _col(df, "close", "Close")
    high = _col(df, "high", "High")
    low = _col(df, "low", "Low")
    vwap = _col(df, "VWAP", "vwap", "Vwap")
    if any(x is None for x in (close, high, low, vwap)) or len(close) < 4:
        return False, "need candle/VWAP confirmation data"
    try:
        c1, c2 = _f(close.iloc[-2]), _f(close.iloc[-1])
        v1, v2 = _f(vwap.iloc[-2]), _f(vwap.iloc[-1])
        if None in (c1, c2, v1, v2):
            return False, "invalid candle/VWAP confirmation data"

        s = str(signal or "").upper()
        if "CE" in s or "BUY" in s or "CALL" in s:
            same_side = c1 > v1 and c2 > v2 and c2 >= c1
            fresh_break = c2 > max(_f(high.iloc[-2], c2), _f(high.iloc[-3], c2))
            return same_side and fresh_break, "2 bullish closes + fresh 2-candle swing high break"
        if "PE" in s or "SELL" in s or "PUT" in s:
            same_side = c1 < v1 and c2 < v2 and c2 <= c1
            fresh_break = c2 < min(_f(low.iloc[-2], c2), _f(low.iloc[-3], c2))
            return same_side and fresh_break, "2 bearish closes + fresh 2-candle swing low break"
    except Exception:
        pass
    return False, "direction confirmation unavailable"


def _setup_score(app, signal, df, price):
    try:
        setup = app.compute_weighted_setup(signal, df, price)
    except Exception:
        setup = {}
    score = 0.0
    if isinstance(setup, dict):
        for key in ("score", "weighted_score", "entry_score", "final_score", "ai_score"):
            v = _f(setup.get(key))
            if v is not None:
                score = max(score, v)
    return setup if isinstance(setup, dict) else {}, score


def _key(setup, signal):
    market = ""
    for k in ("index", "index_name", "symbol", "underlying", "instrument"):
        if setup.get(k):
            market = str(setup.get(k)).upper()
            break
    return f"{market}:{str(signal or '').upper()}"


def install(app):
    """Install the guard on the live/paper weighted entry quality gate."""
    base = getattr(app, "core_bridge_weighted_quality_ok", None)
    if not callable(base):
        return False, "core_bridge_weighted_quality_ok not found"

    if getattr(base, "_okai_choppy_guard_v2", False):
        return True, "already installed"

    def guarded(signal, df, price):
        base_ok, base_reason = base(signal, df, price)
        if not base_ok:
            return base_ok, base_reason

        setup, score = _setup_score(app, signal, df, price)
        key = _key(setup, signal)
        chop = assess_chop(df)

        if chop["hard_block"]:
            _RECOVERY_LATCH[key] = True
            flags = ",".join(k for k, v in chop["flags"].items() if v)
            return False, (
                f"CHOPPY blocked {chop['hits']}/{chop['available']} | {flags} "
                f"| ADX={chop['adx'] if chop['adx'] is not None else 'NA'}"
            )

        if _RECOVERY_LATCH.get(key):
            confirm_ok, confirm_reason = _two_candle_recovery_ok(df, signal)
            try:
                normal_required = float(app.config.get("entry_score", app.config.get("score_threshold", 82)) or 82)
            except Exception:
                normal_required = 82.0
            required = min(100.0, normal_required + RECOVERY_SCORE_BONUS)
            if not confirm_ok or score < required:
                return False, (
                    f"CHOP recovery blocked | score {score:.0f}<{required:.0f} or confirmation pending "
                    f"| {confirm_reason}"
                )
            _RECOVERY_LATCH[key] = False
            return True, (
                f"CHOP recovery OK | score {score:.0f}>={required:.0f} | {confirm_reason}"
            )

        return True, base_reason

    guarded._okai_choppy_guard_v2 = True
    app.core_bridge_weighted_quality_ok = guarded

    try:
        app.config["choppy_market_guard"] = True
        app.config["chop_adx_max"] = CHOP_ADX_MAX
        app.config["chop_ema_compression_pct"] = EMA_COMPRESSION_PCT
        app.config["chop_atr_compression_ratio"] = ATR_COMPRESSION_RATIO
        app.config["chop_recovery_score_bonus"] = RECOVERY_SCORE_BONUS
    except Exception:
        pass

    try:
        app.gui_log(
            "OKAI CHOPPY MARKET GUARD V2 active | 3/4 hard block | "
            "ADX<18 | EMA9/21<=0.20% | VWAP chop | ATR<=0.80 baseline | recovery +5 + 2 candles"
        )
    except Exception:
        pass
    return True, "installed"
