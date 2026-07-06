import json, urllib.request, urllib.parse, sys
from pathlib import Path

BASE = "http://127.0.0.1:8765"
TOKEN = "optionking-local"

def check_config():
    print("\n[1] CONFIG / SECRETS")
    cfg = json.loads(Path("users/owner/config.json").read_text(encoding="utf-8"))
    sec = json.loads(Path("users/owner/secrets.json").read_text(encoding="utf-8")) if Path("users/owner/secrets.json").exists() else {}

    ok = True
    for k in ["api_key","client_id","password","totp_secret","telegram_token","chat_id"]:
        v = str(cfg.get(k) or sec.get(k) or "").strip()
        print(k, "=", "SET" if v else "MISSING", "| len", len(v))
        if not v:
            ok = False
    return ok

def get(path):
    req = urllib.request.Request(BASE + path, headers={"X-Api-Token": TOKEN})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode())

def check_api():
    print("\n[2] API")
    ok = True

    for path in ["/phone_server_update.json", "/status", "/trades", "/chart"]:
        try:
            if path == "/phone_server_update.json":
                with urllib.request.urlopen(BASE + path, timeout=8) as r:
                    d = json.loads(r.read().decode())
            else:
                d = get(path)
            print(path, "=", d.get("ok"))
            if not d.get("ok"):
                ok = False
        except Exception as e:
            print(path, "= ERROR", e)
            ok = False

    try:
        st = get("/status").get("data", {})
        print("trade_mode =", st.get("trade_mode"))
        print("nifty =", st.get("nifty") or st.get("nifty_price") or st.get("ltp"))
        print("closed_trades =", st.get("closed_trades") or st.get("trade_count"))

        ch = get("/chart").get("data", {})
        labels_len = len(ch.get("labels") or [])
        close_len = len(ch.get("close") or [])
        nifty_val = float(st.get("nifty") or st.get("nifty_price") or st.get("ltp") or 0)

        print("chart labels =", labels_len)
        print("chart close =", close_len)

        if nifty_val <= 0:
            print("MOBILE STATUS PRICE = FAIL ❌")
            ok = False
        else:
            print("MOBILE STATUS PRICE = OK ✅")

        if close_len <= 0:
            print("MOBILE CHART DATA = FAIL ❌")
            ok = False
        else:
            print("MOBILE CHART DATA = OK ✅")

    except Exception as e:
        print("status/chart detail error:", e)
        ok = False

    return ok

def check_angel():
    print("\n[3] ANGEL DIRECT LOGIN")
    try:
        import pyotp
        from SmartApi import SmartConnect

        cfg = json.loads(Path("users/owner/config.json").read_text(encoding="utf-8"))
        obj = SmartConnect(api_key=str(cfg.get("api_key") or "").strip())
        totp = pyotp.TOTP(str(cfg.get("totp_secret") or "").strip()).now()
        res = obj.generateSession(str(cfg.get("client_id") or "").strip(), str(cfg.get("password") or "").strip(), totp)
        print("login status =", res.get("status"))
        print("login message =", res.get("message"))
        if not res.get("status"):
            return False

        ltp = obj.ltpData("NSE", "NIFTY", "26000")
        print("ltp status =", ltp.get("status"))
        print("ltp =", ((ltp.get("data") or {}).get("ltp")))
        return bool(ltp.get("status"))
    except Exception as e:
        print("Angel error =", e)
        return False

ok1 = check_config()
ok2 = check_api()
ok3 = check_angel()

print("\nFINAL =", "PASS ✅" if (ok1 and ok2 and ok3) else "FAIL ❌")
sys.exit(0 if (ok1 and ok2 and ok3) else 1)
