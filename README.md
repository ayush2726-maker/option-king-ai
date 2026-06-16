# Option King AI Cloud Paper Bot

This is the no-GUI cloud version for paper testing. It runs an HTTP API that the mobile app can control.

## Best No-Cloud Setup: Android Phone Server

Google Cloud/VM hosting can ask for billing details. For paper testing without cloud cost, use a spare Android phone as the server.

See `MOBILE_SERVER.md`.

Quick start in Termux:

```bash
bash termux_setup.sh
nano config.json
bash termux_start.sh
```

Then in the mobile app use:

```text
http://SERVER_PHONE_WIFI_IP:8765
```

or, if app and server are on the same phone:

```text
http://127.0.0.1:8765
```

## Setup On A Free VM

1. Create an Oracle Cloud Always Free Ubuntu VM, Google Cloud Compute Engine VM, or any Ubuntu VPS.
2. Open port `8765` in the cloud firewall/security list.
3. Copy this `cloud_bot` folder to the VM.
4. Install Python packages:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

5. Copy config and fill your Angel details:

```bash
cp config.example.json config.json
nano config.json
```

6. Run:

```bash
python app.py
```

Mobile app URL:

```text
http://YOUR_VM_PUBLIC_IP:8765
```

Token defaults to:

```text
optionking-local
```

## Market Schedule

The bot process can stay running, but trading logic only works during the market window:

- Monday to Friday only
- Uses `Asia/Kolkata` by default, even on a cloud VM
- Analysis starts at `09:15`
- Trading starts at `09:25`
- Normal day trade end is `15:15`
- Expiry day trade end is `15:00`
- Weekends are skipped automatically
- If `auto_start_bot` is `true`, the paper bot starts itself after `09:15` on a working market day.

For exchange holidays, add dates in `config.json`:

```json
"market_holidays": ["2026-01-26", "2026-03-03"]
```

Timezone can be changed with:

```json
"market_timezone": "Asia/Kolkata"
```

## API

- `GET /status`
- `GET /live`
- `GET /risk`
- `GET /reports`
- `GET /settings-info`
- `GET /trades`
- `GET /logs`
- `POST /start`
- `POST /stop`
- `POST /capital`
- `POST /close-position`

This backend is paper-mode only. It does not place live broker orders.

## Same Android Phone As Server

You can run this backend in Termux on the same Android phone where the mobile app is installed.

1. Install Termux from F-Droid.
2. Copy this `cloud_bot` folder to phone storage.
3. In Termux, go to the folder and run:

```bash
bash termux_setup.sh
```

4. Fill `config.json` with Angel details.
5. Start the server:

```bash
bash termux_start.sh
```

6. In the mobile app, tap `This Phone`.

Mobile URL:

```text
http://127.0.0.1:8765
```

Keep Termux running, allow battery unrestricted mode, and use `termux-wake-lock` during market hours.

## Google Cloud

See `GOOGLE_CLOUD.md`.
