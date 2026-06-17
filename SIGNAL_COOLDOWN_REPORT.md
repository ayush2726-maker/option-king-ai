# Signal Cooldown Implementation Report

## Overview
Implemented a duplicate rejected-signal cooldown logic in `app.py` to reduce log spam and prevent repetitive processing of the same blocked setups.

## Changes
- Added a global dictionary `rejected_signals` to track the last rejection state for each signal type (CE/PE).
- Modified `place_paper_trade` to incorporate cooldown checks:
    - **Cooldown Duration:** 20 seconds.
    - **Bypass Conditions:**
        - Signal score changes by 10 or more points.
        - NIFTY price moves by 20 or more points.
- If a signal is rejected and within the cooldown period without meeting bypass conditions, the "QUALITY ENTRY BLOCKED" log, trade suggestion update, and event logging are skipped.

## Verification
- Ran `python -m py_compile app.py` - Success.
- Logic verified via code review:
    - Correctly calculates `time_diff`, `score_diff`, and `nifty_diff`.
    - Updates `rejected_signals` only when logging occurs.
    - Preserves existing entry/exit logic and thresholds.
