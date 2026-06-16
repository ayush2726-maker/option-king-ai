import zipfile, glob, json, os
for z in sorted(glob.glob('data/backups/*.zip'), key=os.path.getmtime, reverse=True)[:12]:
    try:
        with zipfile.ZipFile(z) as archive:
            names = archive.namelist()
            cfg_names = [n for n in names if n.endswith('config.json')]
            line = f"{z}|{os.path.getsize(z)}"
            if cfg_names:
                data = archive.read(cfg_names[0])
                cfg = json.loads(data.decode('utf-8'))
                filled = [k for k in ['api_key','client_id','password','totp_secret','telegram_token','chat_id','api_auth_token','capital'] if str(cfg.get(k) or '').strip()]
                line += '|config=' + cfg_names[0] + '|filled=' + ','.join(filled)
            else:
                line += '|no_config'
            print(line)
    except Exception as exc:
        print(z, 'ERR', exc)
