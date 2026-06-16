# Google Cloud Server Setup

Google Cloud can run the `cloud_bot` paper backend, but signup requires a Google Cloud billing account.

Important:

- Google Cloud Free Trial gives new users `$300` credit for `90 days`.
- Google says you must provide a valid credit card or other payment method during Free Trial signup.
- Compute Engine Free Tier includes one `e2-micro` VM in selected US regions with monthly limits.
- Use this only for paper testing first.

## Recommended Free-Tier VM

Create a Compute Engine VM:

- Region: `us-central1`, `us-east1`, or `us-west1`
- Machine type: `e2-micro`
- OS: Ubuntu 24.04 LTS
- Disk: standard persistent disk, 30 GB or less
- Firewall: allow SSH

After VM is created, add a firewall rule for the mobile API:

- Protocol: TCP
- Port: `8765`
- Source: your IP if possible, otherwise `0.0.0.0/0`

Using `0.0.0.0/0` is easier but less private. Keep `api_auth_token` strong.

## Upload Cloud Bot

From your laptop, copy the `cloud_bot` folder to the VM.

Simple way:

1. Open VM SSH in Google Cloud Console.
2. Use the upload file/folder option, or zip the folder and upload.
3. On VM:

```bash
unzip cloud_bot.zip
cd cloud_bot
```

## Install And Start

Run:

```bash
bash google_cloud_setup.sh
nano config.json
sudo systemctl start optionking-cloud
sudo systemctl status optionking-cloud
```

View logs:

```bash
journalctl -u optionking-cloud -f
```

Restart after config changes:

```bash
sudo systemctl restart optionking-cloud
```

Stop:

```bash
sudo systemctl stop optionking-cloud
```

## Mobile App URL

Use the VM external IP:

```text
http://YOUR_GOOGLE_VM_EXTERNAL_IP:8765
```

Token:

```text
optionking-local
```

or whatever you set in `config.json`.

## Schedule

The process can run all day, but the bot starts/trades only during configured market windows:

- Monday-Friday
- Timezone: `Asia/Kolkata`
- Analysis: `09:15`
- Trading: `09:25`
- Expiry day end: `15:00`
- Normal day end: `15:15`
- Holidays from `market_holidays`

## Config Example

```json
{
  "api_key": "YOUR_ANGEL_API_KEY",
  "client_id": "YOUR_CLIENT_ID",
  "password": "YOUR_PASSWORD",
  "totp_secret": "YOUR_TOTP_SECRET",
  "telegram_token": "",
  "chat_id": "",
  "api_auth_token": "change-this-token",
  "capital": 20000,
  "auto_start_bot": true,
  "market_timezone": "Asia/Kolkata",
  "market_holidays": ["2026-01-26"],
  "host": "0.0.0.0",
  "port": 8765
}
```
