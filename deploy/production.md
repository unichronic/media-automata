# Production Deployment Runbook

This project now expects one persistent production account set: one WhatsApp/OpenWA session, one LinkedIn browser profile, one X browser profile, one Instagram browser profile, and one Instagram Android app-data volume.

## Persistent State

Keep these paths on the server disk or a persistent volume. Losing any of them can force platform re-login or break scheduled jobs.

```text
.env
runtime/media_automata.sqlite3
runtime/storage
runtime/artifacts
runtime/profiles/linkedin/main_brand
runtime/profiles/x/main_brand
runtime/profiles/instagram/main_brand
runtime/redroid-data
runtime/android-backups/instagram-main_brand-latest.tar.gz
```

OpenWA also has its own Docker/session storage outside this repo. Preserve that volume or folder as well; otherwise the WhatsApp session will need QR pairing again. Run the OpenWA API and dashboard containers with Docker restart policy `unless-stopped` so they come back after host reboot.

## Server Prerequisites

Install:

```bash
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv curl git docker.io
curl -LsSf https://astral.sh/uv/install.sh | sh
```

The Instagram native Story path requires a Linux host that can run privileged Docker containers with binder devices for ReDroid. The included `scripts/start_redroid.sh` loads/creates the binder devices and starts `redroid/redroid:11.0.0-latest`.

## App Install

```bash
cd /home/unichronic/media_automata
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"
python -m playwright install chromium
python -m media_automata.cli migrate
```

On a server without a desktop session, set this in `.env` after the persistent browser profiles are already logged in:

```text
APP_BROWSER_HEADLESS=true
```

## Android Runtime

Start ReDroid and verify ADB:

```bash
./scripts/start_redroid.sh
python -m media_automata.cli android-check
```

Restore the latest known-good Instagram Android session before testing:

```bash
python -m media_automata.cli instagram-native-restore
python -m media_automata.cli instagram-native-auth-check
```

If Instagram asks for a code, finish it with:

```bash
python -m media_automata.cli instagram-enter-code 123456
python -m media_automata.cli instagram-native-backup
```

## Systemd User Services

Install the user units using the current repo path:

```bash
./deploy/systemd/install_user_units.sh
loginctl enable-linger "$USER"
systemctl --user enable --now media-automata-redroid.service
systemctl --user enable --now media-automata-api.service
systemctl --user enable --now media-automata-worker.service
systemctl --user enable --now media-automata-monitor.timer
```

Enable the optional hourly deep Instagram native check after the account has stabilized:

```bash
systemctl --user enable --now media-automata-deep-check.timer
```

The worker unit runs `python -m playwright install chromium` before startup, so a lost Playwright browser cache does not break posting again. The monitor timer checks the database, runtime paths, queue state, profile cache, Android backup presence, and OpenWA session. If OpenWA is not ready, it calls the configured session start endpoint and waits for recovery.

## Deployment Verification

```bash
curl -s http://127.0.0.1:8080/health
curl -s "http://127.0.0.1:8080/health/deployment?recover_openwa=true"
curl -s "http://127.0.0.1:8080/health/deployment?recover_openwa=true&deep_instagram=true"
curl -s http://127.0.0.1:8080/accounts
python -m media_automata.cli production-check --recover-openwa --deep-instagram
```

Watch logs:

```bash
journalctl --user -u media-automata-api.service -f
journalctl --user -u media-automata-worker.service -f
journalctl --user -u media-automata-monitor.service -n 100
```

## Production Smoke Test

Send a real WhatsApp command from the allowed account/group:

```text
/post this on all 3 platforms
Instagram caption - smoke test
Twitter - smoke test
LinkedIn - smoke test
```

Then check:

```bash
curl -s http://127.0.0.1:8080/jobs?limit=5
python -m media_automata.cli monitor-once
```

For Instagram feed-post-to-Story:

```text
/post this to Instagram feed and /feed-to-story
Instagram caption - production feed smoke
Story text - new post is live
Story music - suggested
```

## Recovery Rules

If WhatsApp replies stop, run:

```bash
python -m media_automata.cli whatsapp-session-recover
```

If Instagram native app is logged out, run:

```bash
python -m media_automata.cli instagram-native-restore
python -m media_automata.cli instagram-native-auth-check
```

If restore still reaches a verification screen, enter the received code and immediately create a fresh backup:

```bash
python -m media_automata.cli instagram-enter-code 123456
python -m media_automata.cli instagram-native-backup
```

If a Chromium profile was left locked by a crash, the platform workers already remove stale `Singleton*` files before launching. If a database lock remains visible in `/accounts`, wait 30 minutes for the stale lock window or restart the worker after confirming no publish is actively running.
