import datetime as dt
import app
app.apply_live_strategy_runtime_settings()
try:
    app.angel_login()
except Exception as exc:
    print("login", exc)
day = dt.date(2026, 5, 27)
df = app.fetch_backtest_candles(day)
orb = df[(df["clock"] >= app.ORB_START) & (df["clock"] < app.ORB_END)]
if orb.empty:
    orb = df.head(5)
oh = float(orb["high"].max())
ol = float(orb["low"].min())
gap = app.backtest_gap_day_mode(df, day)
print("orb", oh, ol, "gap", gap, "rows", len(df))
for target in ["10:05", "10:39", "11:09", "11:59", "12:53", "14:14", "14:34"]:
    hh, mm = map(int, target.split(":"))
    idxs = df.index[df["clock"] == dt.time(hh, mm)].tolist()
    if not idxs:
        print(target, "no candle")
        continue
    i = idxs[0]
    row = df.iloc[i]
    base = app._OKAI_QUALITY_BASE_BACKTEST_SIGNAL(df, i, oh, ol, gap)
    sig, tt, sc = base
    print("\nTIME", target, "base", base, "close", row["close"])
    if sig:
        approved, q = app._okai_build_trade_quality(sig, df=df.iloc[: i + 1].copy(), price=float(row["close"]), require_premium=False, backtest=True)
        print("quality", q.get("grade"), approved, "score", q.get("score"), "fake", q.get("fake_breakout_probability"), "regime", q.get("market_regime"), "blocks", q.get("blocks"))
        print("components", q.get("components"))
