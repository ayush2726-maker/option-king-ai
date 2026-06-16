import datetime as dt
import os
import re

APP_PATH = "app.py"
VERSION = "2026.05.09-max-order-qty-cap-1"

PATCH = r'''

# ===== OPTION KING AI PATCH: MAX ORDER QTY CAP =====
# Version: 2026.05.09-max-order-qty-cap-1

MAX_ORDER_QTY = 1350


def cap_qty_to_order_limit(qty, lot_size, source="LIVE"):
    try:
        qty = int(qty or 0)
        lot_size = int(lot_size or FAST_LOT_SIZE)
    except Exception:
        return 0, False
    max_qty = int(config.get("max_order_qty", MAX_ORDER_QTY) or MAX_ORDER_QTY)
    capped_raw = min(qty, max_qty)
    capped_qty = (capped_raw // lot_size) * lot_size
    capped = capped_qty != qty
    if capped:
        try:
            gui_log(
                f"Qty capped by max order limit | {source} | Requested {qty} | "
                f"Limit {max_qty} | Lot {lot_size} | Final {capped_qty}"
            )
        except Exception:
            pass
    return max(0, capped_qty), capped


_OKAI_ORIGINAL_GET_QTY = get_qty


def get_qty(premium, trade_type, lot_size):
    qty = _OKAI_ORIGINAL_GET_QTY(premium, trade_type, lot_size)
    capped_qty, _ = cap_qty_to_order_limit(qty, lot_size, "TRADE")
    return capped_qty


_OKAI_ORIGINAL_BACKTEST_QTY = backtest_qty


def backtest_qty(bt_capital, premium, trade_type, lot_size):
    qty, max_lots = _OKAI_ORIGINAL_BACKTEST_QTY(bt_capital, premium, trade_type, lot_size)
    capped_qty, capped = cap_qty_to_order_limit(qty, lot_size, "BACKTEST")
    if capped:
        max_lots = capped_qty // int(lot_size or FAST_LOT_SIZE)
    return capped_qty, max_lots

# ===== END PATCH =====
'''


def main():
    if not os.path.exists(APP_PATH):
        raise SystemExit("app.py not found. Run from /sdcard/Download/cloud_bot")

    text = open(APP_PATH, "r", encoding="utf-8").read()
    if VERSION in text:
        print("Patch already applied:", VERSION)
        return

    backup = f"app.py.bak_max_qty_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"
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


if __name__ == "__main__":
    main()
