import json
import traceback

print('BROKER_ROUTE_TEST_START')
try:
    import app
    app.load_config()
    app.apply_live_strategy_runtime_settings()
    app.angel_login()
    master = app.get_master()
    df = master[
        (master['name'] == 'NIFTY')
        & (master['exch_seg'] == 'NFO')
        & (master['instrumenttype'].astype(str).str.contains('OPT', na=False))
        & (master['symbol'].astype(str).str.endswith('PE'))
    ].copy()
    df['expiry_dt'] = app.parse_expiry_series(df['expiry'])
    df['strike_num'] = app.pd.to_numeric(df['strike'], errors='coerce') / 100
    df = df.dropna(subset=['expiry_dt', 'strike_num'])
    df = app.filter_to_nearest_option_expiry(df, context='broker route test PE')
    wanted = 23000
    sel = df[df['strike_num'] == wanted]
    if sel.empty:
        base = 23400
        sel = df.iloc[(df['strike_num'] - base).abs().argsort()[:1]]
    row = sel.iloc[0]
    option = {
        'symbol': str(row['symbol']),
        'token': str(row['token']),
        'exchange': str(row['exch_seg']),
        'strike': int(float(row['strike_num'])),
        'lot_size': int(float(row['lotsize'])),
    }
    print('OPTION', json.dumps(option))
    params = app.build_live_order_params(option, 'BUY', 1)
    print('PARAMS', json.dumps(params))
    try:
        order_id, response, sent_params = app.place_live_order(option, 'BUY', 1, 'BROKER ROUTE TEST INVALID LOT QTY 1')
        print('UNEXPECTED_ACCEPTED', json.dumps({'order_id': order_id, 'response': response, 'params': sent_params}, default=str))
    except Exception as exc:
        print('BROKER_RESPONSE_OR_REJECT', str(exc))
except Exception as exc:
    print('TEST_SCRIPT_ERROR', repr(exc))
    traceback.print_exc()
print('BROKER_ROUTE_TEST_END')
