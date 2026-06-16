# Option King AI Strategy Notes - 2026-05-09

Current server version after today's patches:
- 2026.05.09-update-check-quiet-1

Important patches already applied on phone server:
- Round-trip charges enabled: buy side + sell side brokerage/charges included in net P&L.
- Cost-lock trailing SL enabled: first profit lock includes round-trip charges plus 5 percent entry buffer.
- Max order quantity cap set to 87,750 qty, equal to 1,350 lots when lot size is 65.
- Candle fetch guard added for weekend/market-closed empty Angel responses.
- Auto-update check disabled/quiet so old laptop update URLs do not show API errors.
- Trade data remains saved date-wise in data/trade_data.

Current live strategy on server:
- HALF rule: VWAP + Supertrend + strong candle momentum + EMA.
- FULL rule: HALF rule + ORB confirmation on normal days.
- Gap day: ORB off, strict HALF only, FULL disabled.
- Score order shown in app: 1 VWAP, 2 Supertrend, 3 EMA, 4 ORB normal-only, 5 Candle.
- Choppy filter: avoids trades when EMA and VWAP are too close.
- Reversal exit: exits when opposite confirmation shows Supertrend/VWAP/ORB/EMA failure.

Prepared but not merged strong-rule engine:
- File: STRONG_CE_PE_RULES.py
- FULL = 5/5: VWAP, Supertrend, previous candle break, 3-candle HH/HL or LH/LL, volume above previous 5 average.
- HALF = 4/5 if core direction passes and one secondary confirmation is missing.
- CE hard block below VWAP. PE hard block above VWAP.
- SL from recent swing or Supertrend line.
- Target at 1:1.5 risk reward.
- Trailing after 1R.
- Extra debug reasons for every skip or entry.

Difference:
- Current server strategy is more practical and already integrated with the app/backtest/telegram.
- Strong-rule engine is stricter and should reduce random entries, but it may take fewer trades.
- Strong-rule engine still needs merge/testing before replacing current live get_signal logic.

Do not forget:
- Before live trading, keep paper forward test first.
- Do not rebuild APK after every server-only patch unless mobile UI text/features changed.
- Apply strategy changes to phone server first; desktop/mobile apps mostly read server status.
