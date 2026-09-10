"""Option King AI startup wrapper.

Imports the existing app, installs the independent choppy-market entry guard,
then starts the unchanged application main function.
"""

import app
from choppy_market_guard import install


if __name__ == "__main__":
    ok, reason = install(app)
    try:
        app.gui_log(f"Choppy guard startup: {ok} | {reason}")
    except Exception:
        pass
    app.main()
