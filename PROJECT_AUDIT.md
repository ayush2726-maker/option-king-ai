# Project Audit: Option King AI Cloud Bot

## 1. Project Architecture
The project follows a **Monolithic Architecture** for the core bot logic, wrapped in a **Multi-User Proxy Gateway**.

- **Core Logic (`app.py`):** A massive, single-file application (~20,000 lines) that handles everything from API communication, technical analysis, strategy execution, to order management. It uses a "monkey-patching" approach where newer versions of functions are appended to the end of the file, wrapping previous definitions.
- **Gateway Layer (`multi_user_gateway.py`):** An isolation layer that manages multiple users by spawning separate `app.py` processes in dedicated user directories. This provides data isolation but leads to high resource duplication.
- **Communication:** Uses a standard `http.server` (BaseHTTPRequestHandler) for a REST API that interfaces with a mobile application.
- **Data Persistence:** Relies on local JSON and CSV files in the `data/` directory for capital state, trade history, and caching.

## 2. Folder Structure
```text
cloud_bot/
├── app.py (Core Monolith)
├── multi_user_gateway.py (Proxy/Manager)
├── STRONG_CE_PE_RULES.py (Clean Strategy Module - Not fully integrated)
├── config.json (User configuration)
├── data/
│   ├── angel_cache/ (Instrument masters)
│   ├── trade_data/ (Daily trade logs)
│   └── capital_state.json (Equity tracking)
├── logs/ (Daily execution logs)
├── users/ (Isolated worker environments)
├── requirements.txt (Dependencies)
└── [Many .py and .sh patch scripts]
```

## 3. Entry Points
- **Standalone:** `python app.py` (Single user mode)
- **Multi-User:** `python multi_user_gateway.py` (Proxy mode, manages workers)
- **Mobile/Termux:** `bash termux_start.sh` (Launcher for mobile environments)

## 4. Trading Flow
1. **Startup:** `load_config()` -> `load_trade_history_from_disk()` -> `scheduler_loop` starts.
2. **Scheduling:** `scheduler_loop` monitors time (09:15-15:15). Starts `bot_loop` during market hours.
3. **Analysis:** `bot_loop` calls `get_indicators()` every few seconds to fetch OHLC data from Angel One.
4. **Signal Generation:** `get_signal(price)` processes indicators (VWAP, Supertrend, EMA, ORB) to determine entry/exit.
5. **Execution:** `enter_position()` and `close_position()` handle trade lifecycle. 
    - **Paper Mode:** Simulates fills based on LTP.
    - **Live Mode:** (Partially implemented/Patched) Calls `SmartConnect.placeOrder`.
6. **Risk Management:** `trailing_sl_after_1r` and `check_risk_limits` monitor P&L.

## 5. Angel One API Flow
- **Authentication:** `SmartConnect.generateSession` using TOTP.
- **Data Ingestion:** 
    - `getLtpData` for real-time price.
    - `getCandleData` for technical analysis.
    - Instrument Master stored in `OpenAPIScripMaster.json`.
- **Order Management:** `placeOrder`, `modifyOrder`, `getOrderBook`.

## 6. Telegram Flow
- **Alerts:** `send_msg` sends trade notifications and system errors to a configured Chat ID.
- **Control:** `telegram_command_loop` listens for commands like `/start`, `/stop`, `/status` via polling.

## 7. GUI Flow
- **No Native GUI:** The system is headless.
- **Mobile Backend:** Serves a JSON API on port 8765. The "GUI" is a separate mobile app (likely React Native or Flutter) that consumes this API.
- **Console Output:** `gui_log` provides verbose logging in the terminal.

## 8. Mobile Server Flow (Termux)
- Designed to run on spare Android phones.
- Includes `termux-wake-lock` to prevent the OS from killing the process.
- Logic specifically accounts for low-RAM environments with `safe_low_ram_cleanup`.

## 9. All Bugs
- **Session Management:** Logs show frequent `AG8001: Invalid Token` errors. The bot fails to re-authenticate or refresh tokens reliably.
- **Redefinition Soup:** Function `get_signal` is redefined ~10 times, and `close_position` ~6 times. Only the last definition is active, but the chain of `_OKAI_..._BASE` wrappers creates a massive call stack.
- **Global Variable Abuse:** Almost all state is stored in global variables (`position`, `running`, `capital`), leading to high risk of race conditions in a multi-threaded environment.
- **Error Handling:** Many `try-except` blocks are too broad, often just printing the error and continuing, which can lead to inconsistent state.
- **Inconsistent Signal Logic:** Different patches use different indicator sets, making it nearly impossible to audit the actual entry criteria without tracing 20k lines.

## 10. Duplicate Code
- **Massive Redundancy:** Approximately 70% of `app.py` is likely redundant code from previous versions that were never removed, only shadowed by new definitions at the end of the file.
- **Utility Functions:** Multiple versions of `_safe_float`, `_okai_float`, etc., exist throughout the project.

## 11. Dead Code
- **Unreachable Logic:** Thousands of lines in the middle of `app.py` are shadowed by later definitions and are never executed.
- **Old Patches:** Many `termux_apply_..._patch.py` scripts are likely one-time-use and clutter the root directory.

## 12. Performance Issues
- **Startup Latency:** Parsing a 20,000-line Python file on every startup/worker-spawn is extremely inefficient, especially on mobile.
- **Synchronous I/O:** Using `urllib.request` and `BaseHTTPRequestHandler` is blocking. High traffic or slow API responses from the broker can freeze the trading loop.
- **Memory Consumption:** Storing all indicators and trade history in global pandas DataFrames without proper pruning.

## 13. Security Issues
- **Unencrypted API:** The mobile API runs over HTTP. In multi-user mode, credentials and tokens are transmitted in plain text across the network.
- **Credential Storage:** Secrets are stored in plain JSON. While common for local bots, it lacks any encryption at rest.
- **Token Exposure:** `api_auth_token` is the only barrier for the API, and it is frequently logged or displayed in cleartext.

## 14. Missing Features
- **Proper Backtesting Engine:** Current backtesting is rudimentary and lacks slippage/brokerage modeling.
- **Standardized Logging:** Uses `print` and custom `gui_log` instead of Python's `logging` module.
- **Database Integration:** Relies on flat files which are prone to corruption during crashes.
- **Unit/Integration Tests:** Zero automated tests found in the project.

## 15. Strategic Suggestions for Improvement
1. **Modular Refactor:** Split `app.py` into logical modules:
    - `api/`: API routes (FastAPI recommended).
    - `strategy/`: Signal generation logic (incorporate `STRONG_CE_PE_RULES.py`).
    - `broker/`: Angel One wrapper and order management.
    - `core/`: Scheduling and lifecycle management.
2. **Implement Asyncio:** Replace `threading` and `http.server` with `FastAPI` and `httpx` for non-blocking I/O.
3. **Robust Session Management:** Implement a reliable token refresh mechanism that handles `AG8001` errors by automatically re-logging.
4. **Database Migration:** Use SQLite for trade history and state to ensure data integrity.
5. **Modern Configuration:** Use `.env` for secrets and Pydantic for settings validation.
6. **Vectorized Analysis:** Use `talib` or `pandas-ta` for more efficient indicator calculations instead of manual loops.
7. **Clean Versioning:** Remove the "patching by concatenation" strategy. Use Git properly for version history.
8. **Add Tests:** Implement unit tests for strategy signals and integration tests for broker API interaction.
9. **Secure Communication:** Implement HTTPS/SSL for the mobile API.
10. **Centralized Logging:** Use a structured logging framework (like `structlog` or `loguru`) for better observability.
