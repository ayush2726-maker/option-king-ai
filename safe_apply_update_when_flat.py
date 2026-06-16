import json
import os
import py_compile
import signal
import subprocess
import time
import urllib.request

ROOT = "/sdcard/Download/cloud_bot"
APP = os.path.join(ROOT, "app.py")
NEW = os.path.join(ROOT, "app.py.new")
LOG = os.path.join(ROOT, "safe_apply_update_when_flat.log")


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " | " + msg
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def status_payload():
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    token = cfg.get("api_auth_token", "optionking-local")
    req = urllib.request.Request(
        "http://127.0.0.1:8765/status",
        headers={"X-Api-Token": token},
    )
    return json.loads(urllib.request.urlopen(req, timeout=8).read().decode()).get("data", {})


def server_pids():
    out = subprocess.run(["pgrep", "-af", "python"], text=True, capture_output=True).stdout.splitlines()
    pids = []
    me = os.getpid()
    for line in out:
        parts = line.strip().split(maxsplit=1)
        if not parts:
            continue
        try:
            pid = int(parts[0])
        except Exception:
            continue
        cmd = parts[1] if len(parts) > 1 else ""
        if pid != me and " app.py" in cmd:
            pids.append(pid)
    return pids


def apply_update():
    if not os.path.exists(NEW):
        log("No app.py.new found; nothing to apply")
        return False
    py_compile.compile(NEW, doraise=True)
    backup = APP + ".backup_" + time.strftime("%Y%m%d_%H%M%S")
    os.replace(APP, backup)
    os.replace(NEW, APP)
    log("Update moved into app.py; backup=" + backup)
    for pid in server_pids():
        try:
            os.kill(pid, signal.SIGTERM)
            log("Stopped old server pid " + str(pid))
        except Exception as exc:
            log("Stop pid failed " + str(pid) + ": " + str(exc))
    time.sleep(2)
    out = open(os.path.join(ROOT, "server.log"), "ab")
    subprocess.Popen(["nohup", "python", "app.py"], cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
    log("Started updated server")
    return True


log("Safe apply watcher armed")
for _ in range(720):
    try:
        data = status_payload()
        if data.get("position") is None:
            log("Position flat; applying update")
            apply_update()
            raise SystemExit(0)
        pos = data.get("position") or {}
        log("Waiting for flat position: " + str(pos.get("symbol", "OPEN")))
    except Exception as exc:
        log("Check/apply wait: " + str(exc))
    time.sleep(15)
log("Safe apply watcher timed out")
