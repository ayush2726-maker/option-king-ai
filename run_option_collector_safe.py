"""Run the NIFTY option collector without SmartAPI request-body logging.

This wrapper suppresses the SmartAPI/logzero logger before importing the
collector. It does not disable TLS verification and does not alter order logic.
"""

from __future__ import annotations

import logging

try:
    from logzero import logger as logzero_logger

    logzero_logger.setLevel(logging.CRITICAL)
except Exception:
    pass

logging.getLogger("logzero_default").setLevel(logging.CRITICAL)
logging.getLogger("SmartApi").setLevel(logging.CRITICAL)

import collect_nifty_option_candles_v3 as collector


if __name__ == "__main__":
    raise SystemExit(collector.main())
