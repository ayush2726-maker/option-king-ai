# Filter Softening + Paper/Live Sync + HERO_ZERO_EXPIRY — 2026-06-26

This patch implements the 7 requirements from the user:
1. TQU hard block threshold 88 → 68
2. Volume requirement 1.8x → 1.2x
3. SIDEWAYS partial allow (CAUTION mode) when core ≥4/5 & weighted ≥78
4. MTF 5m bearish softened to warning when weighted_score ≥ 78
5. `NO TRADE SUMMARY` log line (rate-limited to 1/min)
6. Paper/Live mode sync — `config["mode"]` and `config["trade_mode"]` now always match; PAPER forces `live_trading_enabled=False`
7. HERO_ZERO_EXPIRY strategy (separate file: `hero_zero_expiry.py`)

Plus existing safety is preserved — nothing was REMOVED, only thresholds softened and one new fallback path added.

## Diff summary (app.py — surgical edits only)

| Location | What changed | Risk |
|---|---|---|
| `_tqu_sideways_min_score()` (line ~21043) | Default `88` → `68`, lower bound `80` → `50` | LOW |
| `_tqu_sideways_check()` (line ~21228) | Hardcoded `1.8x` → configurable (default 1.2x). Added SIDEWAYS CAUTION branch | LOW |
| `compute_weighted_setup()` MTF step (line ~21370) | MTF reject becomes warning when `weighted_score ≥ 78` (config: `tqu_mtf_strong_override`) | LOW |
| `compute_weighted_setup()` end (line ~21414) | Added `_emit_no_trade_summary()` call after each TQU block | NONE |
| New function `_emit_no_trade_summary()` | Compact 1/min rate-limited summary line | NONE |
| `set_trade_mode()` (line ~6395) | Mirrors `mode` ↔ `trade_mode`; PAPER forces `live_trading_enabled=False`; refuses to enable live in PAPER | LOW |

## New configurable knobs (`config.json`)

```json
{
  "tqu_sideways_min_score":    68,
  "tqu_sideways_min_vol_ratio": 1.2,
  "tqu_mtf_strong_override":   78,
  "hero_zero_enabled":         true,
  "hero_zero_sideways_default": "CE"
}
```

All have safe defaults baked into the code; you don't need to add them unless you want to tune.

## New `NO TRADE SUMMARY` log format
```
NO TRADE SUMMARY | reason=SIDEWAYS/TQU/MTF/VOLUME/SCORE | score=42 (weighted=58) | need=68 | vol=1.0x | mode=PAPER
```

## Paper/Live mode fix — behavior

| Action | Old behavior | New behavior |
|---|---|---|
| `set_trade_mode("PAPER")` | only `trade_mode` updated | both `mode` AND `trade_mode` set to PAPER; `live_trading_enabled` forced to False |
| `set_trade_mode("LIVE")` | only `trade_mode` updated | both keys set to LIVE; `live_trading_enabled` unchanged unless explicitly set |
| `set_trade_mode(live_enabled=True)` while in PAPER | silently enabled — could leak live orders | **refused** with a log line; live trading remains off |

## HERO_ZERO_EXPIRY — wiring into `app.py`

The strategy is a **clean separate module** (`hero_zero_expiry.py`) that needs 3 host hooks added to `app.py`:

### 1) One-time init (near the bottom of `app.py`, after main globals are defined)
```python
# ── HERO_ZERO_EXPIRY initialization ──
try:
    from hero_zero_expiry import init as _hero_zero_init
    # Build a tiny "host" namespace exposing the callables the strategy needs.
    class _HZHost:
        config           = config
        lot_size         = LOT_SIZE if 'LOT_SIZE' in dir() else 75
        gui_log          = staticmethod(gui_log)
        market_now       = staticmethod(market_now)
        is_expiry_day    = staticmethod(lambda *a, **kw: bool(is_expiry_day_today()))
        get_atm_strike   = staticmethod(lambda: round(get_ltp(NIFTY_TOKEN) / 50) * 50)
        # Optional helpers — implement any not-yet-existing ones to return safe defaults:
        fetch_option_by_strike = staticmethod(lambda sig, k: _hz_fetch_option(sig, k))
        option_5min_high       = staticmethod(_hz_option_5min_high)
        option_vwap            = staticmethod(_hz_option_vwap)
        option_volume_ratio    = staticmethod(_hz_option_volume_ratio)
        option_last2_candle_low= staticmethod(_hz_option_last2_low)
        index_momentum_signal  = staticmethod(_hz_index_momentum)
        place_order            = staticmethod(_hz_place_order)
        close_position_by_id   = staticmethod(_hz_close_by_id)
        update_position_sl     = staticmethod(_hz_update_sl)
    _HERO_ZERO = _hero_zero_init(_HZHost)
    gui_log("HERO_ZERO_EXPIRY initialized")
except Exception as _e:
    _HERO_ZERO = None
    try: gui_log(f"HERO_ZERO_EXPIRY init failed: {_e}")
    except Exception: pass
```

### 2) Call once per main-loop tick (inside `main_loop()` / wherever you decide entries)
```python
# Before normal entry logic:
if _HERO_ZERO is not None:
    try: _HERO_ZERO.on_loop_tick()
    except Exception as _e: gui_log(f"HERO_ZERO tick error: {_e}")
```

### 3) Bypass the 14:15 EOD cutoff for HERO_ZERO
Find your existing "no new entry after 14:15" guard (look for `new_entries_allowed()` / `EOD_NO_NEW_ENTRY_TIME`). Wrap it:
```python
def new_entries_allowed():
    # Existing 14:15 logic stays as-is
    ok = _existing_new_entries_check()
    if ok:
        return True
    # HERO_ZERO_EXPIRY override
    try:
        if _HERO_ZERO is not None and _HERO_ZERO.can_bypass_no_trade_window():
            return True
    except Exception:
        pass
    return False
```

### Helper stubs the host must provide
Implement these as 5–15 line helpers near where you do option fetches. They need to use your existing Angel One option-chain code:
- `_hz_fetch_option(signal, strike)` → `{symbol, ltp, bid, ask, ltp_age_seconds}`
- `_hz_option_5min_high(symbol)` → float
- `_hz_option_vwap(symbol)` → float
- `_hz_option_volume_ratio(symbol)` → float
- `_hz_option_last2_low(symbol)` → float (lowest low of last 2 option candles)
- `_hz_index_momentum()` → `"BULL_BREAK" | "BEAR_BREAK" | "SIDEWAYS"`
- `_hz_place_order(side, option, qty, mode)` → `{order_id}` (route through your existing buy fn)
- `_hz_close_by_id(pos_id, reason)` and `_hz_update_sl(pos_id, new_sl, reason)`

Most of these likely exist already with slightly different names — just thin wrappers.

## Verification checklist (paper mode, expiry day)

1. After 14:30: log line `HERO ZERO ENTRY | CE/PE <strike> @ <premium> qty=<N> sl=<sl> mode=PAPER` should appear when conditions met.
2. If conditions fail: `HERO ZERO BLOCK | reason=<specific>` appears (no silent skip).
3. At 15:25: `HERO ZERO FORCE EXIT | ...` for every open position.
4. At +50% gain: `HERO ZERO TRAIL | old_sl=… new_sl=… high=… stage=BE_LOCK`.
5. After a loss: any further attempt logs `HERO ZERO BLOCK | reason=no re-entry after loss`.
6. `NO TRADE SUMMARY` log line appears at most once/minute during blocked periods.
7. Switching to PAPER via `/mode` endpoint: bot stops sending any live broker orders. Verify by checking subsequent logs do NOT contain `placeOrder` calls to SmartAPI in PAPER mode.

## What was NOT changed (preserved safety)

- ADX filter — unchanged
- Strict EMA/VWAP/Supertrend entry rules — unchanged
- Loss cooldown candles — unchanged
- Capital sizing for the **main** strategy — unchanged (only HERO_ZERO has its own ₹2000 cap)
- Auto-exit timings — unchanged for main strategy
- AG8001 session refresh — unchanged
