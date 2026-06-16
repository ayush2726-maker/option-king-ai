import datetime as dt
import os
import re

APP_PATH = "app.py"
VERSION = "2026.05.09-roundtrip-cost-trail-1"

PATCH = r'''

# ===== OPTION KING AI PATCH: ROUND-TRIP CHARGES + 5% COST TRAIL =====
# Version: 2026.05.09-roundtrip-cost-trail-1

TRAIL_COST_BUFFER_PERCENT = 5.0


def _okai_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _okai_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


def okai_round_trip_charges(entry_price, exit_price, qty, exchange="NSE"):
    """Buy + sell charges for long option paper trades."""
    entry_price = _okai_float(entry_price)
    exit_price = _okai_float(exit_price)
    qty = _okai_int(qty)
    if entry_price <= 0 or exit_price <= 0 or qty <= 0:
        return {
            "total": 0.0,
            "per_qty": 0.0,
            "buy_total": 0.0,
            "sell_total": 0.0,
            "gst": 0.0,
            "debug": "Charges skipped: invalid entry/exit/qty",
        }

    buy_turnover = entry_price * qty
    sell_turnover = exit_price * qty
    total_turnover = buy_turnover + sell_turnover

    brokerage_per_order = _okai_float(config.get("brokerage_per_order", globals().get("BROKERAGE_PER_ORDER", 20.0)))
    txn_rate = _okai_float(config.get("option_transaction_rate_nse", globals().get("OPTION_TRANSACTION_RATE_NSE", 0.0003552)))
    stt_sell_rate = _okai_float(config.get("option_stt_sell_rate", globals().get("OPTION_STT_SELL_RATE", 0.0015)))
    stamp_buy_rate = _okai_float(config.get("option_stamp_buy_rate", globals().get("OPTION_STAMP_BUY_RATE", 0.00003)))
    sebi_rate = _okai_float(config.get("sebi_charge_rate", globals().get("SEBI_CHARGE_RATE", 10 / 10000000)))
    ipft_rate = _okai_float(config.get("ipft_charge_rate", globals().get("IPFT_CHARGE_RATE", 0.000000001)))
    gst_rate = _okai_float(config.get("gst_rate", globals().get("GST_RATE", 0.18)))

    buy_brokerage = brokerage_per_order
    sell_brokerage = brokerage_per_order
    buy_txn = buy_turnover * txn_rate
    sell_txn = sell_turnover * txn_rate
    buy_sebi = buy_turnover * sebi_rate
    sell_sebi = sell_turnover * sebi_rate
    buy_ipft = buy_turnover * ipft_rate
    sell_ipft = sell_turnover * ipft_rate
    stamp = buy_turnover * stamp_buy_rate
    stt = sell_turnover * stt_sell_rate
    gst = (buy_brokerage + sell_brokerage + buy_txn + sell_txn + buy_sebi + sell_sebi) * gst_rate

    buy_total = buy_brokerage + buy_txn + buy_sebi + buy_ipft + stamp
    sell_total = sell_brokerage + sell_txn + sell_sebi + sell_ipft + stt
    total = buy_total + sell_total + gst
    per_qty = total / qty

    return {
        "total": total,
        "per_qty": per_qty,
        "buy_total": buy_total,
        "sell_total": sell_total,
        "gst": gst,
        "debug": (
            f"Round-trip charges | Buy {buy_total:.2f} + Sell {sell_total:.2f} "
            f"+ GST {gst:.2f} = {total:.2f} | Per qty {per_qty:.2f}"
        ),
    }


def okai_charge_adjusted_cost_lock(entry_price, ltp, qty):
    entry_price = _okai_float(entry_price)
    ltp = _okai_float(ltp)
    charges = okai_round_trip_charges(entry_price, max(entry_price, ltp), qty)
    buffer_amount = entry_price * (TRAIL_COST_BUFFER_PERCENT / 100)
    cost_lock = entry_price + charges["per_qty"] + buffer_amount
    return cost_lock, charges, buffer_amount


def calculate_option_charges(entry_price, exit_price, qty, exchange="NSE"):
    return okai_round_trip_charges(entry_price, exit_price, qty, exchange)


def calculate_trade_charges(entry_price, exit_price, qty, exchange="NSE"):
    return okai_round_trip_charges(entry_price, exit_price, qty, exchange)


def estimate_option_charges(entry_price, exit_price, qty, exchange="NSE"):
    return okai_round_trip_charges(entry_price, exit_price, qty, exchange)


def update_trailing_sl(*args, **kwargs):
    """Charge-adjusted trailing SL. CE and PE are both long option premium trades."""
    global position
    if position is None:
        return

    entry = _okai_float(position.get("entry"))
    ltp = _okai_float(position.get("ltp", entry))
    old_sl = _okai_float(position.get("sl"))
    qty = _okai_int(position.get("qty"))

    if entry <= 0 or ltp <= 0 or qty <= 0:
        return

    if "initial_risk" not in position:
        position["initial_risk"] = abs(entry - old_sl) if old_sl > 0 else entry * (_okai_float(globals().get("SL_PERCENT", 20)) / 100)
    initial_risk = max(_okai_float(position.get("initial_risk")), entry * 0.01)

    cost_lock, charges, buffer_amount = okai_charge_adjusted_cost_lock(entry, ltp, qty)

    if ltp >= cost_lock and position["sl"] < cost_lock:
        position["sl"] = cost_lock
        gui_log(
            f"SL moved to cost+charges+5% | Entry {entry:.2f} | "
            f"Charges/Qty {charges['per_qty']:.2f} | Buffer {buffer_amount:.2f} | "
            f"SL {old_sl:.2f}->{position['sl']:.2f}"
        )

    profit = ltp - entry
    if profit >= initial_risk:
        trail_sl = max(position["sl"], cost_lock, ltp - initial_risk)
        if trail_sl > position["sl"]:
            old = position["sl"]
            position["sl"] = trail_sl
            gui_log(
                f"Trailing SL active after 1R | {position.get('signal', '')} | "
                f"Risk {initial_risk:.2f} | SL {old:.2f}->{position['sl']:.2f}"
            )

# ===== END PATCH =====
'''


def main():
    if not os.path.exists(APP_PATH):
        raise SystemExit("app.py not found. Run from /sdcard/Download/cloud_bot")

    text = open(APP_PATH, "r", encoding="utf-8").read()
    if VERSION in text:
        print("Patch already applied:", VERSION)
        return

    backup = f"app.py.bak_charges_trail_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    with open(backup, "w", encoding="utf-8") as file:
        file.write(text)

    text = re.sub(
        r'SERVER_VERSION\s*=\s*"[^"]+"',
        f'SERVER_VERSION = "{VERSION}"',
        text,
        count=1,
    )

    marker = '\nif __name__ == "__main__":'
    if marker not in text:
        raise SystemExit('Could not find main marker in app.py')

    text = text.replace(marker, PATCH + marker, 1)

    with open(APP_PATH, "w", encoding="utf-8") as file:
        file.write(text)

    import py_compile
    py_compile.compile(APP_PATH, doraise=True)
    print("Patch applied OK:", VERSION)
    print("Backup:", backup)
    print("Now restart server: bash ./termux_start.sh")


if __name__ == "__main__":
    main()
