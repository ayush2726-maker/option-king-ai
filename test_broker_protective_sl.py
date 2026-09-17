import importlib
import types
import unittest

import broker_protective_sl as m

m.time.sleep = lambda *_: None


class FakeBroker:
    def __init__(self):
        self.orders = {}
        self.next_id = 1
        self.modify_calls = []
        self.cancel_calls = []
        self.ltp = 150.0

    def placeOrderFullResponse(self, params):
        oid = str(self.next_id)
        self.next_id += 1
        self.orders[oid] = {**params, "orderid": oid, "orderstatus": "trigger pending"}
        return {"status": True, "data": {"orderid": oid}}

    def modifyOrder(self, params):
        self.modify_calls.append(dict(params))
        oid = str(params["orderid"])
        self.orders[oid].update(params)
        return {"status": True, "data": {"orderid": oid}}

    def cancelOrder(self, order_id, variety):
        self.cancel_calls.append((str(order_id), variety))
        self.orders[str(order_id)]["orderstatus"] = "cancelled"
        return {"status": True}

    def orderBook(self):
        return {"status": True, "data": list(self.orders.values())}

    def ltpData(self, exchange, symbol, token):
        return {"status": True, "data": {"ltp": self.ltp}}


def fake_app(ltp=150.0):
    app = types.SimpleNamespace()
    app.obj = FakeBroker()
    app.obj.ltp = ltp
    app.position = None
    app.logs = []
    app.gui_log = app.logs.append
    app.angel_login = lambda *a, **k: None
    app.build_live_order_params = lambda option, tx, qty: {
        "variety": "NORMAL",
        "tradingsymbol": option["tradingsymbol"],
        "symboltoken": option["symboltoken"],
        "transactiontype": tx,
        "exchange": option["exchange"],
        "ordertype": "MARKET",
        "producttype": "CARRYFORWARD",
        "duration": "DAY",
        "price": "0",
        "quantity": str(qty),
    }
    app._okai_fresh_option_ltp = lambda option, reason, max_age_seconds=0: app.obj.ltp

    def open_base(signal, premium, trade_type, option, qty, mode, live_order_id="", live_order_response=None):
        app.position = {"sl": 128.0, "qty": qty, "mode": mode}
        return app.position

    app._open_position_after_entry = open_base

    def trail_base(new_sl=None):
        if new_sl is not None:
            app.position["sl"] = new_sl
        return app.position["sl"]

    app.update_trailing_sl = trail_base

    def close_base(*args, **kwargs):
        app.position = None
        return True

    app.close_position = close_base
    return app


OPT = {"exchange": "NFO", "tradingsymbol": "NIFTY22SEP2623350CE", "symboltoken": "12345"}


class Tests(unittest.TestCase):
    def test_live_entry_arms_broker_stop(self):
        app = fake_app(150)
        ok, _ = m.install(app)
        self.assertTrue(ok)
        pos = app._open_position_after_entry("BUY", 136.15, "CE", OPT, 65, "LIVE")
        self.assertEqual(pos["_broker_sl_trigger"], 128.0)
        self.assertEqual(pos["_broker_sl_state"], "ACTIVE")
        oid = pos["_broker_sl_order_id"]
        self.assertEqual(app.obj.orders[oid]["ordertype"], "STOPLOSS_MARKET")
        self.assertEqual(app.obj.orders[oid]["triggerprice"], "128.00")

    def test_trail_modifies_same_order_and_never_loosens(self):
        app = fake_app(150)
        m.install(app)
        pos = app._open_position_after_entry("BUY", 136.15, "CE", OPT, 65, "LIVE")
        oid = pos["_broker_sl_order_id"]
        app.update_trailing_sl(132.0)
        self.assertEqual(pos["_broker_sl_order_id"], oid)
        self.assertEqual(pos["_broker_sl_trigger"], 132.0)
        self.assertEqual(len(app.obj.modify_calls), 1)
        app.update_trailing_sl(130.0)
        self.assertEqual(pos["_broker_sl_trigger"], 132.0)
        self.assertEqual(len(app.obj.modify_calls), 1)

    def test_breached_fresh_ltp_exits_instead_of_invalid_modify(self):
        app = fake_app(150)
        m.install(app)
        app._open_position_after_entry("BUY", 136.15, "CE", OPT, 65, "LIVE")
        app.obj.ltp = 126.85
        app.update_trailing_sl(128.5)
        self.assertIsNone(app.position)
        self.assertEqual(len(app.obj.modify_calls), 0)
        self.assertTrue(app.obj.cancel_calls)

    def test_paper_trade_untouched(self):
        app = fake_app(150)
        m.install(app)
        pos = app._open_position_after_entry("BUY", 136.15, "CE", OPT, 65, "PAPER")
        self.assertNotIn("_broker_sl_order_id", pos)
        app.update_trailing_sl(132.0)
        self.assertFalse(app.obj.orders)


if __name__ == "__main__":
    unittest.main()
