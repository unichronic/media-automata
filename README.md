# Media Automata

WhatsApp-controlled browser-agent automation for publishing to LinkedIn, X/Twitter, and Instagram through real browser sessions.

The MVP is Python-based:

- FastAPI command API
- OpenWA-compatible WhatsApp webhook and reply adapter
- LangGraph-style agent orchestration
- Mistral Large LLM provider
- Browser Use plus deterministic Playwright platform workers
- local SQLite development database
- local artifact and media storage

## Quick Start

The venv is not mandatory. It is the recommended setup because Browser Use and Playwright install a fairly large dependency graph. To install into the active Python environment instead, replace `uv pip install -e ".[dev]"` with `uv pip install --system -e ".[dev]"`.

```bash
cp .env.example .env
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"
python -m playwright install chromium
python -m media_automata.cli migrate
uvicorn media_automata.api:app --host 0.0.0.0 --port 8080 --reload
```

Set these in `.env` before sending real commands:

```text
MISTRAL_API_KEY=...
OPENWA_BASE_URL=http://localhost:2785/api
OPENWA_API_KEY=...
OPENWA_SESSION_ID=<OpenWA session UUID>
APP_ALLOWED_WHATSAPP_NUMBERS=*

LINKEDIN_EMAIL=...
LINKEDIN_PASSWORD=...
X_LOGIN_IDENTIFIER=...
X_SECONDARY_IDENTIFIER=...
X_PASSWORD=...
INSTAGRAM_USERNAME=...
INSTAGRAM_PASSWORD=...
```

Process queued platform tasks:

```bash
python -m media_automata.cli worker --loop
```

Browser execution uses Browser Use + Playwright + Mistral through the project-local Browser Use Mistral adapter; the current model is fixed in code to `mistral-large-latest`. Deterministic Playwright worker paths are integrated for LinkedIn text posts, X single posts, Instagram feed posts, and Instagram Stories. `X_SECONDARY_IDENTIFIER` is optional and is used when X asks for an alternate email/phone during suspicious-login verification.
For production auth, the worker uses persistent browser profiles first and only falls back to the optional platform credentials when a profile is logged out. MFA, captcha, OTP, checkpoint, or suspicious-login screens stop the task with `LOGIN_REQUIRED`/`CAPTCHA_OR_VERIFICATION` for manual takeover.
The browser launch path hardens session persistence by reusing the same profile directory, removing stale Chromium lock files left by hard shutdowns, and using stable keychain/password-store flags. A normal browser close or laptop restart should preserve cookies; platform-side security invalidation can still force a fresh login.

## Production Profile Setup

For the single-account deployment, keep these profile directories on a persistent volume and log in once with a headful browser session:

```text
runtime/profiles/linkedin/main_brand
runtime/profiles/x/main_brand
runtime/profiles/instagram/main_brand
```

Use `/accounts` from WhatsApp or `GET /accounts` to see profile paths, lock state, last auth status, and whether credential fallback is configured.

Systemd unit templates for a single-machine production deployment are in `deploy/systemd/`. The full production runbook is in `deploy/production.md`.

Create `runtime/KILL_SWITCH` to pause new publish commands without stopping status or account inspection.

## Local Reference Findings

- `/home/unichronic/postificus` has useful browser hardening patterns in `internal/browser/browser.go`: persistent profile roots, browser flags, human typing helpers, and media upload preparation.
- `/home/unichronic/bentham-mca-api` already has a Node/Puppeteer/stealth stack installed. It is useful as a reference for browser dependency setup, but this project now uses Python Browser Use + Playwright.

## Main Endpoints

- `POST /webhooks/whatsapp`
- `GET /jobs/{job_id}`
- `POST /jobs/{job_id}/retry`
- `POST /worker/run-once`
- `GET /health`
- `GET /health/deployment?recover_openwa=true&deep_instagram=true`
- `POST /whatsapp/session/recover`

## WhatsApp Command Example

```text
/social publish

Platforms: linkedin, x, instagram
Account: main_brand
Topic: announce the new browser-agent automation system
Tone: technical, confident, concise
Media: use attached image
```

Scheduling is queue-level: a command like `schedule this for May 26 12 PM` stores `scheduled_for` on the job and platform tasks, and workers do not claim those tasks until the due time. Replied-to media is supported when OpenWA includes quoted media in the webhook payload or can recover the quoted message from history, so replying to an older image with `/post this photo...` attaches that image to the job.

Instagram feed and Story are modeled as separate tasks when both are requested:

```text
/post to Instagram feed and also Instagram Story
Use the replied photo and make the caption short.
```
