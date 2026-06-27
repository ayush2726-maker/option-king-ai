"""
HERO_ZERO_EXPIRY — expiry-day, far-from-EOD, capped-capital scalp strategy
==========================================================================

Rules (user spec, 2026-06-26):
- Enable only on expiry day.
- Fresh entry only between 14:30 and 15:00 IST.
- Bypass normal no-trade-after-14:15 rule ONLY for this strategy.
- Force exit all open hero-zero positions at 15:25 IST.
- No re-entry after loss (per day).
- Strike: 1-step OTM only (no far OTM).
- Premium window: 0.50 to 10.00; require breakout above last 5-min high,
  above option VWAP, volume >= 1.2x.
- Capital cap: ₹2000 per trade. qty = floor(2000 / (premium*lot)) * lot.
- Entry direction: CE on bullish breakout, PE on bearish breakdown.
  SIDEWAYS allowed only when core_score>=4/5 and weighted_score>=78.
- Exit: SL 40% below entry premium; no trail before +50%; at +50% move to entry+5%;
  at +100% lock +50% min; trail by last 2 option-candle low/high + 25% from peak;
  after +200% aggressive 20% trail; force exit at 15:25.

This module is import-safe. It exposes a single object `HERO_ZERO` with methods
the main `app.py` event loop should call. All logging routes through the host
app's `gui_log` and broker through host's broker functions.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, time as dtime
from typing import Optional, Any

# ─── Config constants (override via config.json hero_zero_*) ──────────────────
HZ_ENTRY_START      = dtime(14, 30)
HZ_ENTRY_END        = dtime(15,  0)
HZ_FORCE_EXIT       = dtime(15, 25)

HZ_MAX_CAPITAL      = 2000.0
HZ_PREMIUM_MIN      = 0.50
HZ_PREMIUM_MAX      = 10.00
HZ_VOL_MIN_RATIO    = 1.2
HZ_INITIAL_SL_PCT   = 0.40   # 40% below entry premium
HZ_BE_TRIGGER_PCT   = 0.50   # at +50% move SL to entry +5%
HZ_BE_NEW_SL_PCT    = 0.05
HZ_LOCK_TRIGGER_PCT = 1.00   # at +100% lock min +50%
HZ_LOCK_MIN_PCT     = 0.50
HZ_AGGRESSIVE_PCT   = 2.00   # +200% -> 20% trail from high
HZ_TRAIL_PEAK_25    = 0.25
HZ_TRAIL_PEAK_20    = 0.20


def _now_ist() -> dtime:
    """Returns current IST time-of-day. Falls back to host market_now() if provided."""
    return datetime.now().time()


class _HeroZeroState:
    """Per-day state for the strategy. Reset each trading day by the host loop."""
    def __init__(self):
        self.day_key: str = ""
        self.had_loss_today: bool = False
        self.positions = []          # list of open HZ positions

    def ensure_day(self, key: str):
        if key != self.day_key:
            self.day_key = key
            self.had_loss_today = False
            self.positions = []


class HeroZeroExpiry:
    """
    Main entry point used by app.py.

    Host (app.py) must inject callable hooks:
      - host.gui_log(msg)
      - host.is_expiry_day(now_dt=None)        -> bool
      - host.market_now()                       -> datetime
      - host.config                             -> dict
      - host.get_atm_strike()                   -> int
      - host.fetch_option(symbol)               -> dict with ltp / iv / oi etc
      - host.option_5min_high(option_symbol)    -> float
      - host.option_vwap(option_symbol)         -> float
      - host.option_volume_ratio(option_symbol) -> float
      - host.index_momentum_signal()            -> "BULL_BREAK" / "BEAR_BREAK" / "SIDEWAYS"
      - host.place_order(side, option, qty, mode)
      - host.close_position_by_id(pos_id, reason)
      - host.update_position_sl(pos_id, new_sl, reason)
      - host.lot_size                           -> int
    """

    def __init__(self, host):
        self.host = host
        self.state = _HeroZeroState()

    # ── Public lifecycle hooks called from app.py loop ────────────────────────

    def on_loop_tick(self):
        """Call every main-loop iteration during market hours."""
        now = self._market_now()
        self.state.ensure_day(now.strftime("%Y-%m-%d"))

        # 1) Force-exit window
        if now.time() >= HZ_FORCE_EXIT:
            self._force_exit_all("HERO ZERO FORCE EXIT 15:25")
            return

        # 2) Manage open positions (trail / SL)
        for pos in list(self.state.positions):
            self._manage_position(pos)

        # 3) Maybe place a new entry
        self._maybe_enter(now)

    def can_bypass_no_trade_window(self) -> bool:
        """app.py asks: can HERO_ZERO override the normal 14:15 cutoff?"""
        if not self._enabled():
            return False
        now = self._market_now().time()
        return HZ_ENTRY_START <= now < HZ_ENTRY_END

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _enabled(self) -> bool:
        try:
            cfg = self.host.config or {}
            if not bool(cfg.get("hero_zero_enabled", True)):
                return False
            return bool(self.host.is_expiry_day())
        except Exception:
            return False

    def _market_now(self) -> datetime:
        try:
            return self.host.market_now()
        except Exception:
            return datetime.now()

    def _log(self, msg: str):
        try:
            self.host.gui_log(msg)
        except Exception:
            print(msg)

    def _lot(self) -> int:
        try:
            return int(self.host.lot_size or 75)
        except Exception:
            return 75

    def _trade_mode(self) -> str:
        try:
            cfg = self.host.config or {}
            return str(cfg.get("trade_mode", cfg.get("mode", "PAPER")) or "PAPER").upper()
        except Exception:
            return "PAPER"

    # ── Entry logic ───────────────────────────────────────────────────────────

    def _maybe_enter(self, now: datetime):
        if not self._enabled():
            return
        tod = now.time()
        if not (HZ_ENTRY_START <= tod < HZ_ENTRY_END):
            return
        if self.state.had_loss_today:
            self._log("HERO ZERO BLOCK | reason=no re-entry after loss")
            return
        if self.state.positions:
            return  # one HZ position at a time

        # Direction decision
        try:
            direction = str(self.host.index_momentum_signal() or "").upper()
        except Exception:
            direction = ""

        signal: Optional[str] = None
        if direction == "BULL_BREAK":
            signal = "CE"
        elif direction == "BEAR_BREAK":
            signal = "PE"
        elif direction == "SIDEWAYS":
            # Allow only with strong core + weighted scores (set on host)
            cfg = self.host.config or {}
            core = float(cfg.get("last_core_score", 0) or 0)
            wgt  = float(cfg.get("last_weighted_score", 0) or 0)
            if core >= 4 and wgt >= 78:
                # In sideways, default to lighter CE bias unless host says otherwise
                signal = str(cfg.get("hero_zero_sideways_default", "CE") or "CE").upper()
                self._log(f"HERO ZERO sideways allowed: core={core:.0f}/5 weighted={wgt:.0f}")
            else:
                self._log(f"HERO ZERO BLOCK | reason=sideways weak (core={core:.0f}/5 wgt={wgt:.0f})")
                return
        else:
            self._log(f"HERO ZERO BLOCK | reason=no clear direction ({direction or 'NONE'})")
            return

        # Strike (1-step OTM)
        try:
            atm = int(self.host.get_atm_strike())
        except Exception as e:
            self._log(f"HERO ZERO BLOCK | reason=cannot determine ATM ({e})")
            return
        step = int((self.host.config or {}).get("strike_step", 50))
        strike = atm + step if signal == "CE" else atm - step

        # Fetch option + filters
        option = self._fetch_option(signal, strike)
        if not option:
            self._log(f"HERO ZERO BLOCK | reason=option fetch failed {signal} {strike}")
            return

        premium = float(option.get("ltp", 0) or 0)
        if not (HZ_PREMIUM_MIN <= premium <= HZ_PREMIUM_MAX):
            self._log(f"HERO ZERO BLOCK | reason=premium {premium:.2f} out of [{HZ_PREMIUM_MIN}-{HZ_PREMIUM_MAX}]")
            return

        # Stale / spread filter
        bid = float(option.get("bid", 0) or 0)
        ask = float(option.get("ask", 0) or 0)
        if bid > 0 and ask > 0:
            spread_pct = (ask - bid) / max(1e-6, (ask + bid) / 2)
            if spread_pct > 0.15:
                self._log(f"HERO ZERO BLOCK | reason=wide spread {spread_pct*100:.0f}%")
                return

        ts_age = float(option.get("ltp_age_seconds", 0) or 0)
        if ts_age and ts_age > 10:
            self._log(f"HERO ZERO BLOCK | reason=stale LTP age={ts_age:.0f}s")
            return

        # 5-min high breakout + VWAP + Volume
        try:
            high5 = float(self.host.option_5min_high(option.get("symbol")) or 0)
            vwap  = float(self.host.option_vwap(option.get("symbol")) or 0)
            vol_r = float(self.host.option_volume_ratio(option.get("symbol")) or 0)
        except Exception as e:
            self._log(f"HERO ZERO BLOCK | reason=indicator fetch failed ({e})")
            return

        if high5 > 0 and premium <= high5:
            self._log(f"HERO ZERO BLOCK | reason=no premium breakout (ltp={premium:.2f}, 5m-high={high5:.2f})")
            return
        if vwap > 0 and premium <= vwap:
            self._log(f"HERO ZERO BLOCK | reason=premium below option VWAP ({premium:.2f} <= {vwap:.2f})")
            return
        if vol_r and vol_r < HZ_VOL_MIN_RATIO:
            self._log(f"HERO ZERO BLOCK | reason=low volume {vol_r:.2f}x < {HZ_VOL_MIN_RATIO}x")
            return

        # Capital-capped sizing
        lot = self._lot()
        per_lot_cost = premium * lot
        if per_lot_cost <= 0:
            self._log("HERO ZERO BLOCK | reason=invalid lot cost")
            return
        max_lots = int(math.floor(HZ_MAX_CAPITAL / per_lot_cost))
        qty = max_lots * lot
        if qty < lot:
            self._log(
                f"HERO ZERO BLOCK | reason=qty<lot (max_capital={HZ_MAX_CAPITAL}, "
                f"per_lot={per_lot_cost:.2f}, lot={lot})"
            )
            return

        # Place order — with extra LIVE-mode preflight
        mode = self._trade_mode()
        if mode == "LIVE":
            # LIVE preflight: re-fetch LTP fresh + final sanity checks
            try:
                fresh = self._fetch_option(signal, strike) or {}
                fresh_ltp = float(fresh.get("ltp", 0) or 0)
                if not (HZ_PREMIUM_MIN <= fresh_ltp <= HZ_PREMIUM_MAX):
                    self._log(f"HERO ZERO BLOCK | reason=LIVE preflight: fresh LTP {fresh_ltp:.2f} out of range")
                    return
                # If LTP jumped >10% since initial check, skip (slippage protection)
                if abs(fresh_ltp - premium) / max(0.01, premium) > 0.10:
                    self._log(f"HERO ZERO BLOCK | reason=LIVE preflight: LTP jumped >10% ({premium:.2f}->{fresh_ltp:.2f})")
                    return
                premium = fresh_ltp
                option["ltp"] = fresh_ltp
                # Re-check capital cap with fresh premium
                per_lot_cost = premium * lot
                max_lots = int(math.floor(HZ_MAX_CAPITAL / per_lot_cost))
                qty = max_lots * lot
                if qty < lot:
                    self._log(f"HERO ZERO BLOCK | reason=LIVE preflight: fresh qty<lot after price move")
                    return
            except Exception as e:
                self._log(f"HERO ZERO BLOCK | reason=LIVE preflight error ({e})")
                return

        try:
            order = self.host.place_order("BUY", option, qty, mode)
        except Exception as e:
            self._log(f"HERO ZERO BLOCK | reason=order placement failed ({e})")
            return

        if not order or not order.get("order_id"):
            self._log(f"HERO ZERO BLOCK | reason=broker returned empty order id (mode={mode})")
            return

        pos = {
            "id": order.get("order_id") or f"HZ-{int(time.time())}",
            "symbol": option.get("symbol"),
            "signal": signal,
            "strike": strike,
            "entry_premium": premium,
            "qty": qty,
            "lot": lot,
            "sl": premium * (1.0 - HZ_INITIAL_SL_PCT),
            "high_premium": premium,
            "stage": "INIT",
            "entry_time": self._market_now().isoformat(),
            "mode": mode,
        }
        self.state.positions.append(pos)
        self._log(
            f"HERO ZERO ENTRY | {signal} {strike} @ {premium:.2f} qty={qty} "
            f"sl={pos['sl']:.2f} (40% below) mode={mode}"
        )

    # ── Position management ───────────────────────────────────────────────────

    def _manage_position(self, pos):
        try:
            opt = self._fetch_option(pos["signal"], pos["strike"])
            ltp = float(opt.get("ltp", 0) or 0) if opt else 0.0
        except Exception:
            return
        if ltp <= 0:
            return

        entry = float(pos["entry_premium"])
        gain_pct = (ltp - entry) / entry
        pos["high_premium"] = max(pos["high_premium"], ltp)

        new_sl = pos["sl"]
        stage  = pos["stage"]
        peak   = pos["high_premium"]

        # +50% — move SL to entry + 5%
        if gain_pct >= HZ_BE_TRIGGER_PCT and stage in ("INIT",):
            new_sl = entry * (1.0 + HZ_BE_NEW_SL_PCT)
            stage  = "BE_LOCK"

        # +100% — lock minimum +50% gain
        if gain_pct >= HZ_LOCK_TRIGGER_PCT and stage in ("INIT", "BE_LOCK"):
            new_sl = max(new_sl, entry * (1.0 + HZ_LOCK_MIN_PCT))
            stage  = "T1_LOCK"

        # After +100%, trail by 25% from peak + last 2 candle low (host-provided)
        if gain_pct >= HZ_LOCK_TRIGGER_PCT:
            trail_floor = peak * (1.0 - HZ_TRAIL_PEAK_25)
            try:
                last2_low = float(self.host.option_last2_candle_low(pos["symbol"]) or 0)
                if last2_low > 0:
                    trail_floor = max(trail_floor, last2_low)
            except Exception:
                pass
            new_sl = max(new_sl, trail_floor)

        # +200% — aggressive 20% trail
        if gain_pct >= HZ_AGGRESSIVE_PCT:
            new_sl = max(new_sl, peak * (1.0 - HZ_TRAIL_PEAK_20))
            stage  = "AGGRESSIVE_TRAIL"

        # Apply SL update if it moved
        if new_sl > pos["sl"] + 0.01:
            self._log(
                f"HERO ZERO TRAIL | {pos['signal']} {pos['strike']} "
                f"old_sl={pos['sl']:.2f} new_sl={new_sl:.2f} high={peak:.2f} stage={stage}"
            )
            try:
                self.host.update_position_sl(pos["id"], new_sl, f"HERO_ZERO_{stage}")
            except Exception:
                pass
            pos["sl"]    = new_sl
            pos["stage"] = stage

        # SL hit
        if ltp <= pos["sl"]:
            self._exit_position(pos, f"SL hit @ {ltp:.2f} (sl={pos['sl']:.2f})", loss=(ltp < entry))

    def _exit_position(self, pos, reason: str, loss: bool = False):
        try:
            self.host.close_position_by_id(pos["id"], reason)
        except Exception:
            pass
        self._log(f"HERO ZERO EXIT | {pos['signal']} {pos['strike']} | {reason}")
        if loss:
            self.state.had_loss_today = True
        try:
            self.state.positions.remove(pos)
        except ValueError:
            pass

    def _force_exit_all(self, reason: str):
        for pos in list(self.state.positions):
            try:
                self.host.close_position_by_id(pos["id"], reason)
            except Exception:
                pass
            self._log(f"HERO ZERO FORCE EXIT | {pos['signal']} {pos['strike']} | {reason}")
        self.state.positions.clear()

    # ── Option fetch wrapper ──────────────────────────────────────────────────

    def _fetch_option(self, signal: str, strike: int) -> Optional[dict]:
        try:
            # Some hosts prefer (signal, strike) tuple, others a constructed symbol
            return self.host.fetch_option_by_strike(signal, strike)
        except AttributeError:
            try:
                sym = self.host.build_option_symbol(signal, strike)
                return self.host.fetch_option(sym)
            except Exception:
                return None
        except Exception:
            return None


# ─── Module-level singleton helper ────────────────────────────────────────────
HERO_ZERO: Optional[HeroZeroExpiry] = None

def init(host) -> HeroZeroExpiry:
    """app.py: `from hero_zero_expiry import init as init_hero_zero` then call once."""
    global HERO_ZERO
    HERO_ZERO = HeroZeroExpiry(host)
    return HERO_ZERO
