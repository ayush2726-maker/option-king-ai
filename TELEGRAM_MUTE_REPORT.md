# Telegram Error Mute Report

## Changes
- Added a global variable `last_telegram_error_ts` to track the last time a Telegram error was logged.
- Updated `_send_msg_sync` to implement a 5-minute (300 seconds) cooldown for logging Telegram send failures or errors.
- Added a "(muted for 5m)" note to the exception log message for clarity.
- Ensured that trading logic is not affected by Telegram communication issues.
- Prevented repetitive log spam and stack trace printing (by logging only the exception string once every 5 minutes).

## Verification
- `python -m py_compile app.py` executed successfully.
- Code review confirms that Telegram messages will still be attempted, but errors will only be logged sparingly.
