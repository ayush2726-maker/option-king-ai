import os, signal, time
killed=[]
me=os.getpid()
for name in os.listdir('/proc'):
    if not name.isdigit():
        continue
    pid=int(name)
    if pid == me:
        continue
    try:
        raw=open(f'/proc/{pid}/cmdline','rb').read()
    except Exception:
        continue
    parts=[p for p in raw.split(b'\0') if p]
    if parts and parts[0].endswith(b'python') and parts[-1] == b'app.py':
        try:
            os.kill(pid, signal.SIGTERM)
            killed.append(pid)
        except Exception:
            pass
print('killed', killed)
time.sleep(1)
