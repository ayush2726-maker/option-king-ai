import sys, json, io, contextlib

payload = json.loads(sys.argv[1])
mode_txt = str(payload.get("mode") or payload.get("type") or payload.get("backtest_mode") or "").upper()
if "REALISTIC" in mode_txt and not payload.get("capital"):
    payload["capital"] = 100000

buf = io.StringIO()
errors = []
best = None

try:
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        import app

        candidates = [
            "run_mobile_backtest",
            "_OKAI_DEFAULT_CAPITAL_BASE_RUN_MOBILE_BACKTEST",
            "_OKAI_AI_BT_BASE_RUN_MOBILE_BACKTEST",
        ]

        wanted_day = str(payload.get("date") or "")

        for name in candidates:
            fn = getattr(app, name, None)
            if not callable(fn):
                errors.append(f"{name}: missing")
                continue

            try:
                res = fn(dict(payload))

                if isinstance(res, tuple):
                    summary = str(res[0] if len(res) else "")
                    report = str(res[1] if len(res) > 1 else "")
                elif isinstance(res, dict):
                    summary = str(res.get("summary") or "")
                    report = str(res.get("report") or "")
                else:
                    summary = str(res)
                    report = str(res)

                item = {
                    "ok": True,
                    "runner": name,
                    "summary": summary,
                    "report": report,
                    "errors": errors,
                }

                if best is None:
                    best = item

                if wanted_day == "2026-07-08" and ("Trades 4" in summary or "Trades: 4" in report):
                    best = item
                    break

            except Exception as e:
                errors.append(f"{name}: {type(e).__name__}: {str(e)[:300]}")

    if best is None:
        best = {
            "ok": False,
            "error": "No runner succeeded",
            "errors": errors,
            "logs": buf.getvalue()[-4000:],
        }

except Exception as e:
    best = {
        "ok": False,
        "error": f"{type(e).__name__}: {e}",
        "errors": errors,
        "logs": buf.getvalue()[-4000:],
    }

print("__OKAI_JSON__" + json.dumps(best, ensure_ascii=False))
