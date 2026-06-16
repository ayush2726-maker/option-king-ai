import os, glob, json
candidates=[]
for pattern in ["**/config*.json", "**/*.bak*", "**/*backup*.json", "**/*.zip"]:
    candidates.extend(glob.glob(pattern, recursive=True))
seen=[]
for p in candidates:
    if p in seen or not os.path.isfile(p):
        continue
    seen.append(p)
    try:
        st=os.stat(p)
        filled=""
        if p.lower().endswith('.json'):
            try:
                cfg=json.load(open(p))
                filled_keys=[k for k in ["api_key","client_id","password","totp_secret","telegram_token","chat_id"] if str(cfg.get(k) or '').strip()]
                filled=" filled="+",".join(filled_keys)
            except Exception as exc:
                filled=" json_error"
        print(f"{p}|{st.st_size}|{st.st_mtime:.0f}{filled}")
    except Exception as exc:
        print(p, exc)
