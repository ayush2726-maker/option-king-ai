#!/data/data/com.termux/files/usr/bin/python
import base64, json, os, sys, urllib.request, hashlib, py_compile, subprocess, time

APP_DIR = os.path.abspath(os.path.dirname(__file__))
os.chdir(APP_DIR)
CONFIG_PATH = os.path.join(APP_DIR, 'config.json')
APP_PATH = os.path.join(APP_DIR, 'app.py')
APP_URLS = ['http://100.112.194.74:8790/app.py', 'http://192.168.29.14:8790/app.py', 'http://192.168.1.11:8790/app.py']
EXPECTED_SHA = 'ad15af18ff83b0b203da9aa6588d085dbd9fbdcd92270db0865ed494d7d2010a'
EXPECTED_SIZE = 226938
CONFIG_PATCH = json.loads(base64.b64decode('eyJhcGlfa2V5IjoiUVhCWm9FQ3oiLCJjbGllbnRfaWQiOiJBQUNIMjg2ODkwIiwicGFzc3dvcmQiOiI5MjAxIiwidG90cF9zZWNyZXQiOiJJVFJTUENMV05NRjJJRjdFSFJRTjZEWFhNTSIsInRlbGVncmFtX3Rva2VuIjoiODM2ODUyNTU5NjpBQUZTUklGaUYxcU1IS09pVVY2elNFSU5jVGVEYmVRc3JDdyIsImNoYXRfaWQiOiI2OTU4OTcwMzEyIiwiYXBpX2F1dGhfdG9rZW4iOiJvcHRpb25raW5nLWxvY2FsIiwiYXV0b191cGRhdGVfZW5hYmxlZCI6dHJ1ZSwidXBkYXRlX21hbmlmZXN0X3VybHMiOlsiaHR0cDovLzEwMC4xMTIuMTk0Ljc0Ojg3OTAvcGhvbmVfc2VydmVyX3VwZGF0ZS5qc29uIl0sImF1dG9fdXBkYXRlX2ludGVydmFsX3NlY29uZHMiOjMwMCwiaGFsZl90cmFkZV9xdHlfcGVyY2VudCI6OTAsInJlZW50cnlfYmxvY2tfbWludXRlcyI6NSwicG9zdF9leGl0X3dhaXRfbWludXRlcyI6MSwic3RvcF9hbmRfcmV2ZXJzZV9jb29sZG93bl9taW51dGVzIjo1LCJob3N0IjoiMC4wLjAuMCIsInBvcnQiOjg3NjV9').decode('utf-8'))

def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception:
        return {}

def save_json(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)

def get_status_capital():
    try:
        req = urllib.request.Request('http://127.0.0.1:8765/status', headers={'X-Api-Token': CONFIG_PATCH.get('api_auth_token','optionking-local')})
        data = json.loads(urllib.request.urlopen(req, timeout=5).read().decode('utf-8'))
        return data.get('data', {}) if data.get('ok') else {}
    except Exception:
        return {}

def download_app():
    last = None
    for url in APP_URLS:
        try:
            print('Downloading updated app.py:', url)
            req = urllib.request.Request(url, headers={'User-Agent': 'OptionKingAI-final-installer'})
            data = urllib.request.urlopen(req, timeout=30).read()
            if EXPECTED_SIZE and len(data) != EXPECTED_SIZE:
                raise RuntimeError('size mismatch %s != %s' % (len(data), EXPECTED_SIZE))
            got = hashlib.sha256(data).hexdigest()
            if got != EXPECTED_SHA:
                raise RuntimeError('sha mismatch ' + got)
            tmp = APP_PATH + '.new'
            with open(tmp, 'wb') as f:
                f.write(data)
            py_compile.compile(tmp, doraise=True)
            if os.path.exists(APP_PATH):
                bak = os.path.join(APP_DIR, 'app.py.bak_' + time.strftime('%Y%m%d_%H%M%S'))
                with open(APP_PATH, 'rb') as src, open(bak, 'wb') as dst:
                    dst.write(src.read())
                print('Backup:', bak)
            os.replace(tmp, APP_PATH)
            print('app.py updated OK')
            return
        except Exception as exc:
            last = exc
            print('Download failed:', exc)
    raise SystemExit('Could not download app.py: ' + str(last))

def update_config():
    old = load_json(CONFIG_PATH)
    status = get_status_capital()
    merged = dict(old)
    for k, v in CONFIG_PATCH.items():
        if v not in (None, ''):
            merged[k] = v
    if status.get('capital') is not None:
        merged['capital'] = status.get('capital')
    elif old.get('capital') is not None:
        merged['capital'] = old.get('capital')
    if old.get('market_holidays') is not None:
        merged['market_holidays'] = old.get('market_holidays')
    merged['last_manual_restore'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    save_json(CONFIG_PATH, merged)
    json.load(open(CONFIG_PATH, 'r', encoding='utf-8'))
    print('config.json restored OK')
    print('Auto update ON | Half 90% | Re-entry 5m | Post-exit 1m | Stop-reverse 5m')

def restart_server():
    try:
        subprocess.run(['pkill', '-f', 'python.*app.py'], timeout=5)
    except Exception:
        pass
    print('Starting phone server now...')
    os.execv(sys.executable, [sys.executable, APP_PATH])

if __name__ == '__main__':
    update_config()
    download_app()
    restart_server()