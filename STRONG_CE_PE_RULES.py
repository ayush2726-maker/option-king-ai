"""
Option King AI - Strong CE/PE entry rule engine.

Use this inside the existing bot after get_indicators() has created:
open, high, low, close, volume, VWAP, EMA9, EMA21, Supertrend, SupertrendDirection

Half/Full:
- FULL = all strong conditions pass.
- HALF = core direction passes but 1 secondary confirmation is missing.
- NONE = weak/random setup.
"""

import datetime as dt


FIRST_MINUTES_AVOID = 5
FULL_SCORE_REQUIRED = 5
HALF_SCORE_REQUIRED = 4
RISK_REWARD = 1.5
TRAIL_COST_BUFFER_PERCENT = 5.0

BROKERAGE_PER_ORDER = 20.0
OPTION_TRANSACTION_RATE_NSE = 0.0003552
OPTION_STT_SELL_RATE = 0.0015
OPTION_STAMP_BUY_RATE = 0.00003
SEBI_CHARGE_RATE = 10 / 10000000
IPFT_CHARGE_RATE = 0.000000001
GST_RATE = 0.18


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _supertrend_dir(row):
    for key in ("SupertrendDirection", "SUPERTREND_DIR", "supertrend_dir"):
        value = str(row.get(key, "")).upper()
        if value in ("UP", "BUY", "BULLISH", "1", "TRUE"):
            return "BUY"
        if value in ("DOWN", "SELL", "BEARISH", "-1", "FALSE"):
            return "SELL"
    return "UNKNOWN"


def _supertrend_line(row):
    for key in ("Supertrend", "SUPERTREND", "supertrend"):
        value = row.get(key)
        if value is not None:
            return _safe_float(value)
    return None


def _recent_swing_low(df, lookback=5):
    recent = df.tail(lookback)
    return _safe_float(recent["low"].min())


def _recent_swing_high(df, lookback=5):
    recent = df.tail(lookback)
    return _safe_float(recent["high"].max())


def _higher_high_higher_low(df):
    last3 = df.tail(3)
    if len(last3) < 3:
        return False
    highs = list(last3["high"].astype(float))
    lows = list(last3["low"].astype(float))
    return highs[0] < highs[1] < highs[2] and lows[0] < lows[1] < lows[2]


def _lower_high_lower_low(df):
    last3 = df.tail(3)
    if len(last3) < 3:
        return False
    highs = list(last3["high"].astype(float))
    lows = list(last3["low"].astype(float))
    return highs[0] > highs[1] > highs[2] and lows[0] > lows[1] > lows[2]


def _volume_above_average(df, lookback=5):
    if len(df) < lookback + 1:
        return False, 0.0, 0.0
    current_volume = _safe_float(df.iloc[-1]["volume"])
    average_volume = _safe_float(df.iloc[-(lookback + 1):-1]["volume"].astype(float).mean())
    return current_volume > average_volume, current_volume, average_volume


def _first_minutes_block(now_time, trade_start=dt.time(9, 15)):
    start_dt = dt.datetime.combine(dt.date.today(), trade_start)
    now_dt = dt.datetime.combine(dt.date.today(), now_time)
    return dt.timedelta(0) <= (now_dt - start_dt) < dt.timedelta(minutes=FIRST_MINUTES_AVOID)


def assess_strong_ce_pe_signal(df, now_time=None, trade_start=dt.time(9, 15)):
    """
    Returns:
    {
      signal: CE/PE/None,
      trade_type: FULL/HALF/NONE,
      score: int,
      confidence: int,
      sl: float or None,
      target: float or None,
      risk: float or None,
      reasons: list[str],
      skip_reasons: list[str],
    }
    """
    reasons = []
    skip_reasons = []

    if df is None or len(df) < 8:
        return _decision(None, "NONE", 0, 0, None, None, None, reasons, ["Need at least 8 candles"])

    if now_time is None:
        now_time = dt.datetime.now().time()

    if _first_minutes_block(now_time, trade_start):
        return _decision(None, "NONE", 0, 0, None, None, None, reasons, ["First 5 minutes avoided"])

    last = df.iloc[-1]
    prev = df.iloc[-2]
    close = _safe_float(last["close"])
    high = _safe_float(last["high"])
    low = _safe_float(last["low"])
    prev_high = _safe_float(prev["high"])
    prev_low = _safe_float(prev["low"])
    vwap = _safe_float(last.get("VWAP"))
    st_dir = _supertrend_dir(last)
    st_line = _supertrend_line(last)
    volume_ok, current_volume, average_volume = _volume_above_average(df, 5)

    ce_checks = {
        "price_close_above_vwap": close > vwap,
        "supertrend_buy": st_dir == "BUY",
        "break_previous_high": high > prev_high or close > prev_high,
        "higher_high_higher_low": _higher_high_higher_low(df),
        "volume_above_5_avg": volume_ok,
    }

    pe_checks = {
        "price_close_below_vwap": close < vwap,
        "supertrend_sell": st_dir == "SELL",
        "break_previous_low": low < prev_low or close < prev_low,
        "lower_high_lower_low": _lower_high_lower_low(df),
        "volume_above_5_avg": volume_ok,
    }

    ce_score = sum(1 for ok in ce_checks.values() if ok)
    pe_score = sum(1 for ok in pe_checks.values() if ok)

    # Hard blocks: CE never below VWAP, PE never above VWAP.
    if close <= vwap:
        skip_reasons.append(f"CE blocked: close {close:.2f} <= VWAP {vwap:.2f}")
    if close >= vwap:
        skip_reasons.append(f"PE blocked: close {close:.2f} >= VWAP {vwap:.2f}")

    if ce_score >= pe_score and ce_checks["price_close_above_vwap"] and ce_checks["supertrend_buy"]:
        missing = [name for name, ok in ce_checks.items() if not ok]
        signal = "CE"
        score = ce_score
        trade_type = "FULL" if score >= FULL_SCORE_REQUIRED else "HALF" if score >= HALF_SCORE_REQUIRED else "NONE"
        if trade_type == "NONE":
            skip_reasons.append("CE skipped: score below HALF threshold")
        else:
            reasons.extend([f"CE OK: {name}" for name, ok in ce_checks.items() if ok])
            if missing:
                reasons.append("CE missing for FULL: " + ", ".join(missing))
        sl_candidates = [_recent_swing_low(df, 5)]
        if st_line is not None and st_line < close:
            sl_candidates.append(st_line)
        sl = max([value for value in sl_candidates if value and value < close], default=_recent_swing_low(df, 5))
        risk = max(close - sl, 0.0)
        target = close + (risk * RISK_REWARD) if risk > 0 else None
        confidence = 90 if trade_type == "FULL" else 74 if trade_type == "HALF" else 0
        return _decision(signal if trade_type != "NONE" else None, trade_type, score, confidence, sl, target, risk, reasons, skip_reasons)

    if pe_checks["price_close_below_vwap"] and pe_checks["supertrend_sell"]:
        missing = [name for name, ok in pe_checks.items() if not ok]
        signal = "PE"
        score = pe_score
        trade_type = "FULL" if score >= FULL_SCORE_REQUIRED else "HALF" if score >= HALF_SCORE_REQUIRED else "NONE"
        if trade_type == "NONE":
            skip_reasons.append("PE skipped: score below HALF threshold")
        else:
            reasons.extend([f"PE OK: {name}" for name, ok in pe_checks.items() if ok])
            if missing:
                reasons.append("PE missing for FULL: " + ", ".join(missing))
        sl_candidates = [_recent_swing_high(df, 5)]
        if st_line is not None and st_line > close:
            sl_candidates.append(st_line)
        sl = min([value for value in sl_candidates if value and value > close], default=_recent_swing_high(df, 5))
        risk = max(sl - close, 0.0)
        target = close - (risk * RISK_REWARD) if risk > 0 else None
        confidence = 90 if trade_type == "FULL" else 74 if trade_type == "HALF" else 0
        return _decision(signal if trade_type != "NONE" else None, trade_type, score, confidence, sl, target, risk, reasons, skip_reasons)

    skip_reasons.append(f"No clean setup | CE score {ce_score}/5 | PE score {pe_score}/5 | ST {st_dir} | Vol {current_volume:.0f}/{average_volume:.0f}")
    return _decision(None, "NONE", max(ce_score, pe_score), 0, None, None, None, reasons, skip_reasons)


def _decision(signal, trade_type, score, confidence, sl, target, risk, reasons, skip_reasons):
    return {
        "signal": signal,
        "trade_type": trade_type,
        "score": score,
        "confidence": confidence,
        "sl": sl,
        "target": target,
        "risk": risk,
        "reasons": reasons,
        "skip_reasons": skip_reasons,
        "debug": " | ".join(reasons or skip_reasons),
    }


def round_trip_charges(entry_premium, exit_premium, qty, exchange="NSE"):
    """
    Estimate option round-trip charges for BUY + SELL.

    Brokerage applies on both orders.
    Transaction/SEBI/IPFT apply on buy + sell turnover.
    Stamp duty applies on buy side.
    STT applies on sell side for options.
    GST applies on brokerage + transaction + SEBI charges.
    """
    entry_premium = _safe_float(entry_premium)
    exit_premium = _safe_float(exit_premium)
    qty = int(_safe_float(qty))
    if entry_premium <= 0 or exit_premium <= 0 or qty <= 0:
        return {
            "total": 0.0,
            "per_qty": 0.0,
            "buy_total": 0.0,
            "sell_total": 0.0,
            "debug": "No charges: invalid premium/qty",
        }

    buy_turnover = entry_premium * qty
    sell_turnover = exit_premium * qty
    total_turnover = buy_turnover + sell_turnover

    buy_brokerage = BROKERAGE_PER_ORDER
    sell_brokerage = BROKERAGE_PER_ORDER
    transaction = total_turnover * OPTION_TRANSACTION_RATE_NSE
    sebi = total_turnover * SEBI_CHARGE_RATE
    ipft = total_turnover * IPFT_CHARGE_RATE
    stamp = buy_turnover * OPTION_STAMP_BUY_RATE
    stt = sell_turnover * OPTION_STT_SELL_RATE
    gst = (buy_brokerage + sell_brokerage + transaction + sebi) * GST_RATE

    buy_total = buy_brokerage + (buy_turnover * OPTION_TRANSACTION_RATE_NSE) + (buy_turnover * SEBI_CHARGE_RATE) + (buy_turnover * IPFT_CHARGE_RATE) + stamp
    sell_total = sell_brokerage + (sell_turnover * OPTION_TRANSACTION_RATE_NSE) + (sell_turnover * SEBI_CHARGE_RATE) + (sell_turnover * IPFT_CHARGE_RATE) + stt
    total = buy_total + sell_total + gst

    return {
        "total": total,
        "per_qty": total / qty,
        "buy_total": buy_total,
        "sell_total": sell_total,
        "gst": gst,
        "debug": (
            f"Round-trip charges | Buy {buy_total:.2f} + Sell {sell_total:.2f} "
            f"+ GST {gst:.2f} = {total:.2f} | Per qty {total / qty:.2f}"
        ),
    }


def charge_adjusted_cost_lock(entry_premium, current_premium, qty):
    """
    First protective trail level:
    entry + buy/sell round-trip charges per qty + 5% buffer.
    """
    entry_premium = _safe_float(entry_premium)
    current_premium = _safe_float(current_premium)
    charges = round_trip_charges(entry_premium, max(current_premium, entry_premium), qty)
    buffer_amount = entry_premium * (TRAIL_COST_BUFFER_PERCENT / 100)
    cost_lock = entry_premium + charges["per_qty"] + buffer_amount
    return cost_lock, charges, buffer_amount


def trailing_sl_after_1r(position, current_premium):
    """
    Enable trailing after 1R.
    position needs: entry, sl, signal
    """
    entry = _safe_float(position.get("entry"))
    current_premium = _safe_float(current_premium)
    old_sl = _safe_float(position.get("sl"))
    signal = position.get("signal")
    qty = int(_safe_float(position.get("qty", 0)))
    risk = abs(entry - old_sl)
    if risk <= 0:
        return old_sl, "No trail: invalid risk"

    cost_lock, charges, buffer_amount = charge_adjusted_cost_lock(entry, current_premium, qty)
    if current_premium >= cost_lock and old_sl < cost_lock:
        return cost_lock, (
            f"SL moved to charge-adjusted cost | Entry {entry:.2f} + "
            f"round-trip charges/qty {charges['per_qty']:.2f} + "
            f"5% buffer {buffer_amount:.2f} = {cost_lock:.2f} | {charges['debug']}"
        )

    if signal == "CE":
        profit = current_premium - entry
        if profit < risk:
            return old_sl, "No trail: profit below 1R"
        new_sl = max(old_sl, cost_lock, current_premium - risk)
        return new_sl, f"CE trail active after 1R | SL {old_sl:.2f}->{new_sl:.2f}"

    if signal == "PE":
        # Long PE option profit also means option premium rises, so trail premium upward.
        profit = current_premium - entry
        if profit < risk:
            return old_sl, "No trail: profit below 1R"
        new_sl = max(old_sl, cost_lock, current_premium - risk)
        return new_sl, f"PE trail active after 1R | SL {old_sl:.2f}->{new_sl:.2f}"

    return old_sl, "No trail: unknown signal"
