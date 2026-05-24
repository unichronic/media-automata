# WhatsApp-Controlled Browser Agent Social Automation

## 1. Goal

Build a WhatsApp-driven agent system that receives natural-language publishing instructions, reasons about the required actions, generates platform-specific content, and operates LinkedIn, X/Twitter, and Instagram through real browser sessions.

The system does not use official LinkedIn, X/Twitter, Instagram, or WhatsApp Business APIs for social publishing. It uses browser automation for the platform actions and hosted API keys for LLM and optional browser-agent infrastructure.

## 2. Product Flow

### Primary User Flow

1. User sends a WhatsApp command.
2. WhatsApp gateway receives the message and forwards it to the backend.
3. Command parser extracts intent, platforms, content instructions, media, account selection, and execution mode.
4. Planner agent converts the command into a structured job.
5. Content agent generates platform-specific copy.
6. Platform router creates execution tasks for LinkedIn, X/Twitter, and Instagram.
7. Browser agents open the target platforms using persistent logged-in browser profiles.
8. Browser agents compose, upload media, publish or schedule, and collect result evidence.
9. System sends a final status report back to WhatsApp with post URLs, screenshots, and any failures.

### Example WhatsApp Command

```text
/social publish

Platforms: linkedin, x, instagram
Account: main_brand
Topic: announce our new WhatsApp-controlled AI browser automation system
Tone: technical, confident, concise
Media: use attached image

LinkedIn: make it professional and explain the workflow
X: short punchy launch post
Instagram: caption with 8 relevant hashtags
```

### Example Parsed Job

```json
{
  "job_type": "social_publish",
  "requested_by": "whatsapp:+919999999999",
  "mode": "publish",
  "platforms": ["linkedin", "x", "instagram"],
  "account": "main_brand",
  "topic": "announce our new WhatsApp-controlled AI browser automation system",
  "tone": "technical, confident, concise",
  "media": [
    {
      "kind": "image",
      "source": "whatsapp_attachment",
      "asset_id": "asset_01J..."
    }
  ],
  "platform_instructions": {
    "linkedin": "make it professional and explain the workflow",
    "x": "short punchy launch post",
    "instagram": "caption with 8 relevant hashtags"
  }
}
```

## 3. High-Level Architecture

```text
WhatsApp User
  |
  v
WhatsApp Gateway
  |
  v
Command API
  |
  v
Agent Orchestrator
  |
  +--> Command Parser Agent
  +--> Content Agent
  +--> Platform Router
  +--> Browser Execution Coordinator
  |
  v
Job Queue / Workflow Engine
  |
  +--> LinkedIn Browser Worker
  +--> X/Twitter Browser Worker
  +--> Instagram Browser Worker
  |
  v
Browser Runtime
  |
  +--> Persistent LinkedIn Profile
  +--> Persistent X Profile
  +--> Persistent Instagram Profile
  |
  v
Artifacts
  |
  +--> Screenshots
  +--> Traces
  +--> Browser logs
  +--> Result URLs
  |
  v
WhatsApp Status Reply
```

## 4. Core Technology Choices

### Agent Layer

Use LangGraph for the high-level agent graph.

Reasons:

- It models the system as explicit nodes and edges instead of a loose chain of prompts.
- It supports durable, inspectable state across parsing, content generation, routing, execution, and verification.
- It makes retries and per-platform branches easier to reason about.
- It can call Browser Use, Playwright, and internal tools as graph nodes.

### Browser Agent Layer

Use Browser Use for adaptive browser reasoning and deterministic Playwright for the brittle publishing actions already mapped with stable selectors.

Reasons:

- It is designed for LLM-controlled browser operation.
- It sits naturally on top of Playwright.
- It can use external hosted LLM APIs.
- It supports custom tools, which allows us to combine autonomous operation with deterministic platform actions.

Browser Use should operate inside platform-specific workers. It should not be a single global agent with all account access and all platform instructions mixed together.

Current implementation note: deterministic Playwright is now integrated into the worker path for LinkedIn text posts, X single posts, Instagram feed posts, and Instagram Stories. Browser Use remains available inside the platform workers for adaptive recovery and less-modeled flows such as X threads, while verified publish paths use direct selectors and screenshots.

### Browser Engine

Use Playwright with persistent Chromium profiles.

Reasons:

- Persistent profiles preserve cookies, local storage, IndexedDB, device state, and login sessions.
- Playwright gives deterministic control for file uploads, selectors, screenshots, tracing, and recovery.
- It allows mixing raw selectors with Browser Use decisions.
- Before each launch, stale Chromium `Singleton*` profile lock files are removed. Launch flags keep first-run and local password-store behavior stable so browser closes and laptop restarts do not normally clear sessions.

Profile layout:

```text
runtime/profiles/
  linkedin/main_brand/
  x/main_brand/
  instagram/main_brand/
```

### Workflow Execution

Use Temporal for durable execution if this becomes a serious multi-step system.

Implemented MVP scheduler: SQLite-backed platform tasks include `scheduled_for`; workers claim only tasks with no schedule or a due timestamp.

Alternative for a larger deployment: BullMQ or Celery.

Recommended:

- MVP: SQLite due-task queue + worker processes, with Redis as the next queue upgrade.
- Production: Temporal workflows with per-platform activities.

Temporal is better when jobs may take minutes, browser sessions may fail, or platform tasks need retries.

### Backend

Recommended backend:

```text
Python FastAPI
```

Reasons:

- Browser Use, LangGraph, Pydantic, and Playwright Python fit together cleanly.
- Pydantic gives strong structured outputs for agent plans.
- Python has better ergonomics for agent workflows.

Optional split:

```text
Node.js service for WhatsApp gateway
Python service for agents and browser execution
```

### WhatsApp Gateway

Preferred options:

1. OpenWA
2. whatsapp-web.js
3. Baileys

Recommended practical path:

```text
OpenWA for WhatsApp ingress and outgoing status messages.
```

OpenWA is useful because it already has a gateway shape: sessions, QR auth, webhooks, API keys, media handling, and Docker-oriented deployment.

If the project needs less infrastructure, use `whatsapp-web.js` directly in a small Node service.

### LLM Provider

Use external API keys through a provider abstraction.

Provider adapter interface:

```text
LLMProvider.generate_structured()
LLMProvider.generate_text()
LLMProvider.judge_browser_state()
LLMProvider.rewrite_for_platform()
```

Mistral Large is the configured provider:

```text
MISTRAL_API_KEY=...
MISTRAL_API_KEY1=...
MISTRAL_API_KEY2=...
MISTRAL_API_KEY3=...
```

`MISTRAL_API_KEY` remains valid for a single-key setup. For the current local setup, the three Tradeage keys are loaded as `MISTRAL_API_KEY1-3`; command/content generation starts from slot 1, Instagram browser work starts from slot 2, and LinkedIn/X browser work starts from slot 3. `MISTRAL_API_KEYS` is also supported as a compact comma/space separated list.

Browser Use workers use the project-local Browser Use Mistral adapter with `model="mistral-large-latest"`. It uses plain Mistral JSON mode plus schema instructions and rotates configured keys, because Browser Use's packaged `ChatMistral` adapter returned provider 502s with Mistral `json_schema` response mode in live Instagram tests.

### Storage

Use object storage for artifacts.

MVP:

```text
local filesystem
```

Production:

```text
S3-compatible storage
```

Artifacts:

- WhatsApp attachments
- generated platform copy
- screenshots before and after action
- Playwright traces
- browser console logs
- final result report

### Database

Use Postgres.

Main entities:

- users
- whatsapp_contacts
- accounts
- browser_profiles
- assets
- jobs
- platform_tasks
- agent_messages
- browser_runs
- artifacts
- audit_events

## 5. Agent Design

### Agent Graph

```text
Command Intake
  -> Authorization Check
  -> Command Parser Agent
  -> Content Strategy Agent
  -> Platform Content Agent
  -> Platform Router
  -> Browser Execution Coordinator
  -> Browser Verifier
  -> Result Summarizer
  -> WhatsApp Reply
```

### Command Parser Agent

Purpose:

Turn messy WhatsApp messages into structured intent.

Input:

- message text
- sender number
- quoted message context
- current and quoted/replied-to attachments
- timestamp

Output:

```json
{
  "intent": "publish|schedule|draft|reply|research|status",
  "platforms": ["linkedin", "x", "instagram"],
  "account": "main_brand",
  "topic": "...",
  "mode": "publish",
  "scheduled_for": null,
  "instagram_targets": ["feed", "story"],
  "platform_instructions": {},
  "media_requirements": {},
  "missing_fields": []
}
```

### Content Strategy Agent

Purpose:

Create a content strategy before producing platform text.

Output:

```json
{
  "positioning": "...",
  "audience": "...",
  "angle": "...",
  "cta": "...",
  "style_rules": ["..."]
}
```

### Platform Content Agent

Purpose:

Generate platform-specific content.

LinkedIn output:

```json
{
  "post_text": "...",
  "hashtags": ["..."],
  "media_order": ["asset_01"],
  "posting_target": "personal_profile|company_page"
}
```

X/Twitter output:

```json
{
  "mode": "single|thread",
  "posts": [
    {
      "text": "...",
      "media": ["asset_01"]
    }
  ]
}
```

Instagram output:

```json
{
  "caption": "...",
  "hashtags": ["..."],
  "media": ["asset_01"],
  "post_type": "feed|reel|story"
}
```

### Platform Router

Purpose:

Create independent platform tasks.

If Instagram feed and Instagram Story are both requested, create two Instagram tasks that share the same content/media but differ by `content.mode`.

Task examples:

```json
{
  "task_type": "publish_post",
  "platform": "x",
  "account": "main_brand",
  "content": {
    "text": "...",
    "media": ["asset_01"]
  }
}
```

### Browser Execution Coordinator

Purpose:

Own browser-task lifecycle.

Responsibilities:

- acquire browser profile lock
- start browser session
- run platform worker
- save screenshots and traces
- detect login challenge or blocked state
- report result
- release profile lock

Only one worker should use a given platform/account browser profile at a time.

### Browser Verifier

Purpose:

Verify completion from DOM, screenshot, current URL, and visible page text.

Output:

```json
{
  "status": "success|failed|unknown",
  "confidence": 0.0,
  "result_url": "https://...",
  "evidence": ["artifact_01", "artifact_02"],
  "failure_reason": null
}
```

## 6. Browser Worker Design

### Shared Worker Contract

Every platform worker should implement the same interface:

```python
class PlatformWorker:
    async def setup(self, account: str) -> BrowserSession: ...
    async def publish_post(self, task: PlatformTask) -> PlatformResult: ...
    async def schedule_post(self, task: PlatformTask) -> PlatformResult: ...
    async def create_draft(self, task: PlatformTask) -> PlatformResult: ...
    async def verify_result(self, run: BrowserRun) -> VerificationResult: ...
```

### Worker Execution Phases

```text
1. start_browser
2. check_logged_in
3. navigate_to_composer
4. fill_text
5. upload_media
6. apply_platform_options
7. submit
8. verify
9. capture_artifacts
10. return_result
```

### Browser Use Role

Browser Use should handle:

- navigating dynamic interfaces
- finding UI controls when selectors change
- recovering from unexpected modals
- extracting visible state
- acting on natural-language instructions inside a platform task

Playwright should handle:

- persistent profile startup
- file upload
- screenshots
- tracing
- deterministic selectors when available
- profile locking
- timeout control

### Stagehand Role

Stagehand can be added for reusable, natural-language browser actions where raw selectors are brittle but full autonomy is unnecessary.

Example:

```text
act("Open the post composer")
extract("Return the visible post confirmation URL")
observe("Find the button that publishes the post")
```

Use Stagehand as an enhancement, not as the central orchestration layer.

## 7. Platform Execution Details

### LinkedIn

Supported actions:

- publish text post
- publish post with image
- publish post with document
- choose personal profile or company page
- extract post URL after publishing

Likely browser path:

```text
https://www.linkedin.com/feed/
  -> Start a post
  -> choose account/page if needed
  -> fill editor
  -> upload media
  -> publish
  -> open recent activity/profile
  -> extract result URL
```

Useful reference pattern:

- `personal-linkedin-agent` shows Playwright login state, LinkedIn selectors, structured Pydantic outputs, and evals.

Implementation notes:

- LinkedIn UI changes often; combine stable text/role selectors with Browser Use recovery.
- Company page publishing may need a different route than personal profile publishing.
- Store per-account preferences: personal profile vs company page, default hashtag style, max post length.

### X/Twitter

Supported actions:

- publish single post
- publish thread
- upload image/video
- reply to a post
- quote post
- extract final post URL

Likely browser path:

```text
https://x.com/compose/post
  -> fill [data-testid="tweetTextarea_0"]
  -> upload media through file input
  -> click Post
  -> verify success
```

Useful reference pattern:

- `twitter-mcp` has clean worker separation and persistent profile handling.
- It uses selectors like `[data-testid="tweetTextarea_0"]` and `[data-testid="tweetButton"]`.

Implementation notes:

- Use persistent profile, not only storage state.
- For threads, validate each post length before opening browser.
- Use Browser Use when compose UI or popups change.

### Instagram

Supported actions:

- feed post with image
- carousel post
- story post through mobile-web Story UI when available
- direct media Story through native Android when Story editor actions are requested
- feed-post-to-Story through native Android app automation
- reel upload
- caption and hashtags
- extract profile/result evidence

Likely browser path:

```text
https://www.instagram.com/
  -> Create
  -> Post
  -> Select from computer
  -> file chooser setFiles()
  -> Next
  -> Next
  -> write caption
  -> Share
  -> verify post shared
```

Useful reference pattern:

- `instagram-playwright` demonstrates login storage, file chooser upload, caption entry, screenshots, and duplicate-post metadata.

Implementation notes:

- File upload should use Playwright directly.
- Media preprocessing should happen before browser execution.
- Instagram session expiry should be detected and reported with screenshot artifacts.
- Desktop web currently exposes feed-post creation; mobile web exposes "Your story" and hidden file inputs for Story upload in the live profile. Story publishing has been live-verified through the mobile-web upload flow, with deterministic Playwright upload helpers used for the fragile file-input and publish controls.
- Instagram web does not expose the native "Add post to Story" flow for the tested account/post views. Requests marked as `/feed to story` or `instagram_story_source=feed_post` route to a native Android worker using ADB + Python `uiautomator2`. Direct media Stories with editor actions such as text, link, mention, music, resize, or move also route to this native worker. The default server runtime is ReDroid in Docker with persistent `/data`; the same worker can target an official AVD or any other ADB device by changing `ANDROID_DEVICE_SERIAL` / `ANDROID_ADB_ENDPOINT`.
- ReDroid production uses the x86 Instagram split APK, currently APKPure `389.0.0.49.87`. Earlier ARM APK installs on the x86 runtime caused native SIGSEGV crashes during startup/upload and must not be used for this deployment path.
- The native Android worker grants Instagram camera/audio/media permissions before Story editor runs, opens the exact feed post URL when the feed worker returns one, and falls back to the profile grid only for "latest post" selection. This keeps native Story editor permission prompts and suggested-profile taps out of the normal automation path.
- Feed-post-to-Story remains gated by Instagram's own native share-sheet state. Live Android inspection confirmed `Add to story` can sit several positions away in Instagram's horizontal share carousel, after external/direct-share targets such as WhatsApp, Copy link, Threads, SMS, or Add to channel. The worker scans the carousel in both directions, taps the exact `Add to story` share-button node from the UI hierarchy, and only proceeds when the native Story editor is actually visible.
- When an Instagram feed post and feed-post-to-Story share are in the same job, the feed worker reads the latest profile post URL after a successful share and stores it on the platform result. The worker hydrates the later native Story task with that exact URL before claiming it, avoiding ambiguous "latest post" selection.
- Existing/latest feed-post-to-Story commands are a separate route. Wording such as `/feed-to-story latest post to story`, `latest post to story`, an existing Instagram post URL, or `already posted` creates only an Instagram Story task with `instagram_story_source=feed_post`; it does not create a new Instagram feed task unless the command separately asks for a new feed post.
- The native Android worker treats the foreground app package as part of auth state. It only accepts authenticated UI when `com.instagram.android` is foreground, so Android launcher text such as "Home" or "Search" cannot be mistaken for Instagram navigation. If Instagram crashes or fails to open, the task attempts snapshot recovery and then fails with screenshots/XML artifacts if recovery does not restore foreground Instagram.
- Instagram web auth and Android-native auth are tracked separately. `/accounts` and `GET /accounts` expose native status for Instagram, and native auth checks no longer overwrite browser profile status. After a successful native verification-code login, the helper snapshots `/data/user/0/com.instagram.android` so production can restore a known-good native session after app-data corruption or runtime resets.
- Native publish paths attempt an automatic restore from `runtime/android-backups/instagram-<account>-latest.tar.gz` when Instagram fails to stay foreground. This makes app-data corruption recoverable after one clean native login has been snapshotted. The latest good x86 snapshot is written to `runtime/android-backups/instagram-main_brand-latest.tar.gz`; any snapshot that restores into a crash loop is considered invalid and should not be promoted to `latest`. The verified disaster-recovery behavior is restore-first, then credential fallback if Instagram reports `login_required`; the fallback has completed without OTP in the live drill and writes a fresh `latest` backup after success.
- Instagram Reel mode uses the same real Instagram Create flow as feed posting, but now validates that the media is video, waits longer for video upload/share confirmation, and reports Reel-specific status. This path is implemented for deployment but should be live-smoked with a real video asset before treating Reels as equally proven as image feed/Story.

### Instagram Story Editor Actions

Story formatting is represented as semantic editor actions in `PlatformContent.extra.instagram_story_editor_actions`.
The LLM and deterministic normalizer produce intent-level actions only; the Android worker owns UI selectors,
resource ids, gestures, and coordinate fallbacks.

Supported action types:

```json
[
  {"type": "resize", "target": "post_card|media", "scale": "large|small|full|fit"},
  {"type": "move", "target": "post_card|media", "position": "top|bottom|left|right|center"},
  {"type": "tap_card_variant", "target": "post_card"},
  {"type": "text", "text": "New post is live", "position": "top", "font": "modern", "color": "white"},
  {"type": "mention", "username": "target_account", "position": "bottom"},
  {"type": "link", "url": "auto_feed_post_url", "label": "Open post"},
  {"type": "music", "query": "song name", "section": "best_match"}
]
```

Runtime routing:

- Instagram feed posts use deterministic Playwright desktop-web automation.
- Direct media Stories without editor actions use deterministic Playwright mobile-web upload.
- Direct image Stories with text or @mention actions pre-render those overlays into a 1080x1920 Story image before Instagram opens. This is the production path for reliable formatting. Remaining actions such as music and link still run in the native Android editor.
- Feed-post-to-Story always uses the native Android worker because the tested web UI does not expose this flow.
- `auto_feed_post_url` is resolved after the feed task succeeds and returns the new Instagram post URL.
- `story music: suggested`, `first suggested music`, and equivalent wording select Instagram's first suggested track instead of searching. Specific `story music: <song>` still searches first and falls back to the first visible track.
- Live-verified Story action combinations are direct image pre-rendered text+mention, direct image pre-rendered text+mention plus first-suggested music, link sticker, music search, and feed-post card resize/move/card-style/text. Native clickable mention stickers remain best-effort; direct image Stories render @mentions as visible text for reliability.

## 8. WhatsApp Command Interface

### Command Prefixes

Recommended command prefixes:

```text
/social
/post
/status
/accounts
/retry
```

### Supported Commands

```text
/social publish
/social draft
/social schedule
/social status <job_id>
/social retry <job_id>
/social accounts
/social cancel <job_id>
```

### Message Parsing Rules

The parser should support:

- natural language
- platform-specific sections
- attached media
- quoted messages
- short commands
- follow-up corrections

Example follow-up:

```text
edit x: make it more direct and remove hashtags
```

### WhatsApp Replies

Job accepted:

```text
Job job_123 created.

Platforms:
- LinkedIn: queued
- X: queued
- Instagram: queued
```

Job completed:

```text
Job job_123 completed.

LinkedIn: published
X: published
Instagram: published

Artifacts:
- screenshot bundle: artifact_456
```

## 9. Data Model

### users

```text
id
name
primary_whatsapp_number
role
created_at
updated_at
```

### accounts

```text
id
owner_user_id
platform
account_key
display_name
default_profile_id
status
created_at
updated_at
```

### browser_profiles

```text
id
platform
account_key
profile_path
lock_status
last_used_at
last_login_check_at
status
metadata_json
```

### assets

```text
id
source
mime_type
filename
storage_uri
sha256
width
height
duration_seconds
created_at
```

### jobs

```text
id
requested_by_user_id
whatsapp_message_id
status
mode
raw_command
parsed_intent_json
content_plan_json
created_at
updated_at
completed_at
```

### platform_tasks

```text
id
job_id
platform
account_key
status
task_payload_json
result_json
attempt_count
created_at
updated_at
completed_at
```

### browser_runs

```text
id
platform_task_id
profile_id
status
started_at
completed_at
trace_uri
screenshot_uri
console_log_uri
error_message
```

### audit_events

```text
id
job_id
platform_task_id
event_type
event_payload_json
created_at
```

## 10. API Design

### Command API

```http
POST /webhooks/whatsapp
```

Receives normalized WhatsApp message events.

```http
GET /jobs/{job_id}
```

Returns job state.

```http
POST /jobs/{job_id}/retry
```

Retries failed platform tasks.

```http
POST /accounts/{platform}/{account_key}/login-check
```

Starts a browser session to verify login state.

```http
POST /accounts/instagram/native-check
POST /accounts/instagram/native-login
POST /accounts/instagram/native-backup
POST /accounts/instagram/native-restore
```

Checks, logs in, backs up, or restores the Instagram Android-native session used for feed-post-to-Story and native Story editor flows. The login endpoint uses configured credentials but stops at Instagram verification checkpoints instead of publishing content.

### Internal Worker API

```http
POST /internal/tasks/{task_id}/claim
POST /internal/tasks/{task_id}/heartbeat
POST /internal/tasks/{task_id}/complete
POST /internal/tasks/{task_id}/fail
```

These can be direct DB operations in the MVP.

## 11. Media Pipeline

### Input Sources

- WhatsApp attachments
- URLs in WhatsApp message
- generated images from external providers
- local files uploaded through admin dashboard

### Processing Steps

1. Store original asset.
2. Detect MIME type.
3. Extract image/video metadata.
4. Validate platform constraints.
5. Produce platform-specific variants if needed.
6. Store derived assets.
7. Link assets to platform tasks.

### Platform Media Requirements

Keep this as config, not hard-coded logic:

```yaml
instagram:
  feed_image:
    allowed_types: ["image/jpeg", "image/png"]
    max_files: 10
x:
  image_post:
    allowed_types: ["image/jpeg", "image/png", "image/gif"]
linkedin:
  image_post:
    allowed_types: ["image/jpeg", "image/png"]
```

## 12. Observability

Each browser run should produce:

- structured logs
- screenshots at key steps
- Playwright trace
- browser console log
- final DOM snapshot or accessibility snapshot
- agent reasoning summary
- result URL when available

Minimum screenshots:

```text
01_home_or_composer.png
02_after_text_fill.png
03_after_media_upload.png
04_after_submit.png
05_final_state.png
```

Production health has two levels:

- lightweight checks: database reachability, runtime path writability, queue counts, account cache state, latest Android backup presence, and OpenWA session state
- deep checks: Instagram native Android runtime and auth state, which can start Instagram and should run less frequently than the lightweight monitor

Endpoints and commands:

```text
GET /health
GET /health/deployment?recover_openwa=true
GET /health/deployment?recover_openwa=true&deep_instagram=true
POST /whatsapp/session/recover
media-automata production-check --recover-openwa --deep-instagram
media-automata monitor-once
```

The production monitor runs from `media-automata-monitor.timer` every two minutes. It starts the configured OpenWA session if it is no longer ready and reports sanitized status without returning API keys or platform credentials. The optional deep native timer runs hourly and records Instagram Android auth state separately from browser profile auth state.

## 13. Error Handling

Common failure classes:

```text
LOGIN_REQUIRED
CAPTCHA_OR_VERIFICATION
COMPOSER_NOT_FOUND
MEDIA_UPLOAD_FAILED
CONTENT_REJECTED
PUBLISH_BUTTON_DISABLED
NETWORK_TIMEOUT
UNKNOWN_UI_STATE
```

Each failure should include:

- platform
- account
- current URL
- screenshot
- trace link
- visible page text summary
- suggested retry action

## 14. Configuration

Example environment:

```text
APP_DATABASE_URL=sqlite:///runtime/media_automata.sqlite3
APP_BROWSER_HEADLESS=false

MISTRAL_API_KEY=...
MISTRAL_API_KEY1=...
MISTRAL_API_KEY2=...
MISTRAL_API_KEY3=...

OPENWA_BASE_URL=http://localhost:2785/api
OPENWA_API_KEY=...
OPENWA_SESSION_ID=main

APP_ALLOWED_WHATSAPP_NUMBERS=*

LINKEDIN_EMAIL=...
LINKEDIN_PASSWORD=...
X_LOGIN_IDENTIFIER=...
X_SECONDARY_IDENTIFIER=...
X_PASSWORD=...
INSTAGRAM_USERNAME=...
INSTAGRAM_PASSWORD=...

ANDROID_ADB_ENDPOINT=127.0.0.1:5555
ANDROID_ADB_PATH=/path/to/adb
```

Platform credentials are optional production recovery secrets. The primary auth mechanism is the persistent browser profile volume. Before posting, the worker opens the platform with the profile, checks whether authenticated UI is visible, and posts only after the preflight passes. If the profile is logged out and credentials are configured, Browser Use performs one normal login attempt using redacted sensitive-data placeholders. MFA, OTP, captcha, suspicious login, identity checkpoint, or account-lock screens stop the task and require manual login.

For Instagram feed-post-to-Story and native Story editor actions, browser profiles are not enough because the action is native-app-only in the tested UI. Production should keep the Android `/data` volume persistent so Instagram's native session survives container restarts. On ReDroid, install the x86 Instagram split APK rather than ARM APKs; ARM builds caused SIGSEGV crashes on the x86 runtime. Credentials can recover a plain login screen, but email/SMS verification still stops the job and requires the human to complete the challenge once in the Android runtime. After that challenge is completed, run `media-automata instagram-native-backup` or rely on the automatic post-code snapshot from `media-automata instagram-enter-code`; future runtime resets should use `media-automata instagram-native-restore` before attempting a fresh login. During native Story jobs, the worker also auto-restores the latest snapshot when Instagram crashes or fails to remain foreground.

## 15. Reference Usage

References from `references.md` should be used as implementation guidance:

- `OpenWA`: WhatsApp session gateway, webhooks, outgoing messages, media handling.
- `personal-linkedin-agent`: LinkedIn Playwright patterns, structured agent output, eval-driven decisions.
- `twitter-mcp`: X/Twitter persistent browser profile, read/write tool separation, useful selectors.
- `instagram-playwright`: Instagram media upload, caption flow, login/session handling, screenshots.
- `markudown-mcp`: optional research/scraping tool for content generation, not core publishing.
- Twitter scraping article: useful selectors and scrolling/extraction concepts.

## 16. MVP Scope

MVP should support:

- WhatsApp command intake.
- One authorized WhatsApp user.
- One account per platform.
- External LLM API key.
- Browser Use workers for LinkedIn, X/Twitter, and Instagram, with deterministic Playwright tools for fragile upload/login actions.
- Image upload support.
- Direct publish mode.
- Job status replies over WhatsApp.
- Screenshots and logs per platform task.
- Retry failed platform task.

MVP should not include:

- multi-user permissions
- team dashboard
- advanced scheduling calendar
- analytics
- bulk campaigns
- inbox automation
- account warming

## 17. Production Scope

Production should add:

- deployment health endpoint and CLI monitor
- automatic OpenWA session recovery from monitor/API
- systemd user services for API, worker, ReDroid, and monitor timers
- production backup/restore runbook for profiles, queue DB, OpenWA session, ReDroid data, and Instagram Android snapshots
- multiple WhatsApp users
- multiple social accounts per platform
- dashboard for jobs and artifacts
- calendar UI and advanced schedule management
- platform account health monitoring
- reusable content templates
- memory of successful UI paths
- per-platform posting policies
- trace viewer
- workflow engine durability
- account/profile lock management
- backup and restore of browser profiles

## 18. Key Engineering Principles

- Browser automation is the execution surface.
- Agent outputs must be structured before execution.
- Each platform worker owns its browser profile and platform-specific logic.
- Keep selectors, prompts, and platform constraints configurable.
- Save artifacts for every browser run.
- Use profile locks to prevent two tasks from corrupting the same session.
- Separate content generation from browser operation.
- Separate browser operation from result verification.
- Treat every platform task as independently retryable.
