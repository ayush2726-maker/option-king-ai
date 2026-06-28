# Expiry Selection Engine Fix Report

## Issue
The bot was requesting expired option symbols (e.g., `NIFTY16JUN2623900CE` on June 17, 2026), leading to Angel One error `AB4046` (Symbol token not found). This occurred due to inconsistent date usage (system clock vs market time) and stale scrip master cache.

## Fixes Implemented
1.  **Startup Master Refresh:** Added a call to `get_master()` in the `main()` function to ensure the Angel scrip master is refreshed immediately on bot startup.
2.  **Market-Aware Expiry Filtering:**
    *   Updated `filter_to_nearest_option_expiry` to use `market_now().date()` instead of system local time (`pd.Timestamp.today()`).
    *   Updated `_okai_option_entry_expiry_guard` and `_okai_nifty_expiry_check` to use `market_now().date()` for consistency.
3.  **Immediate Option Regeneration:**
    *   Modified `place_paper_trade` to detect expired or invalid options via `_okai_option_entry_expiry_guard`.
    *   If an option is detected as expired, the bot now immediately calls `get_best_affordable_option` to regenerate a valid active symbol.
4.  **Robust Token Lookup:**
    *   Leveraged existing retry logic in `get_best_affordable_option` which automatically forces a master cache refresh and retries if no valid tradable option is found.
5.  **Validation:**
    *   Ensured nearest active weekly expiry is prioritized by `filter_to_nearest_option_expiry`.

## Verification
- `python -m py_compile app.py` passed successfully.
- Code review confirms that all expiry checks now use the `MARKET_TIMEZONE` aware date, preventing the selection of contracts that expired yesterday but are still in the local cache.
- Regeneration logic ensures that even if a stale option is passed to the entry function, it is replaced before any order is attempted.
