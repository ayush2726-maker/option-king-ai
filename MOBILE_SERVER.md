# Android Phone Server Setup

Use this when Google Cloud is too costly or asks for billing details.

Best setup:

- One spare Android phone = server phone
- Your normal phone = Option King AI mobile app
- Keep both on the same WiFi for local use
- For outside-home use, use Tailscale on both phones if LAN is not available

## Server Phone Install

Install from F-Droid:

- Termux
- Termux:API
- Optional: Termux:Boot

Copy this `cloud_bot` folder to the server phone.

In Termux:

```bash
cd /sdcard/Download/cloud_bot
bash termux_setup.sh
nano config.json
```

Fill:

```json
{
  "api_key": "YOUR_ANGEL_API_KEY",
  "client_id": "YOUR_CLIENT_ID",
  "password": "YOUR_PASSWORD",
  "totp_secret": "YOUR_TOTP_SECRET",
  "api_auth_token": "make-strong-token",
  "capital": 20000,
  "auto_start_bot": true,
  "market_timezone": "Asia/Kolkata",
  "host": "0.0.0.0",
  "port": 8765
}
```

Start:

```bash
bash termux_start.sh
```

Check URL:

```bash
bash termux_status.sh
```

## Mobile App Connect

If the app is on the same phone as Termux:

```text
http://127.0.0.1:8765
```

If the app is on another phone on same WiFi, use the WiFi IP shown by `termux_start.sh`, for example:

```text
http://192.168.1.50:8765
```

Use the same token as `api_auth_token`.

## Keep It Running

On the server phone:

- Keep charger connected during market
- Disable battery optimization for Termux
- Keep WiFi always on
- Keep Termux notification allowed
- Do not clear Termux from recent apps during market

Optional boot auto-start:

```bash
bash termux_boot_setup.sh
```

Then install/open Termux:Boot once and restart the phone.

## Market Timing

The server can stay running, but the bot trades only during market rules:

- Monday-Friday
- Analysis starts `09:15`
- Trade starts `09:25`
- Expiry day trade end `15:00`
- Normal day trade end `15:15`
- Holidays from `market_holidays`

## Notes

- This server is paper-mode only.
- No live broker orders are placed.
- Keep `api_auth_token` private.
- If mobile app says unauthorized, token mismatch hai.
- If mobile app says offline, wrong IP/port, WiFi issue, or Termux server is stopped.
