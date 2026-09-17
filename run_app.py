"""Option King AI startup wrapper.

Imports the existing app, installs runtime safety guards, then starts the
unchanged application main function.
"""

import app
from choppy_market_guard import install as install_choppy_guard
from broker_protective_sl import install as install_broker_protective_sl


if __name__ == "__main__":
    ok, reason = install_choppy_guard(app)
    try:
        app.gui_log(f"Choppy guard startup: {ok} | {reason}")
    except Exception:
        pass

    sl_ok, sl_reason = install_broker_protective_sl(app)
    try:
        app.gui_log(f"Broker SL startup: {sl_ok} | {sl_reason}")
    except Exception:
        pass

    app.main()
