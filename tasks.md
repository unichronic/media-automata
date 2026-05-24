# Project Task Breakdown

Status legend:

- `[x]` Done
- `[~]` Partially done / implemented but not live-verified
- `[ ]` Not done
- `[!]` Blocked by missing external credential, login, or account setup

## Current Snapshot

- [x] Python FastAPI backend scaffolded.
- [x] Browser Use + Playwright installed in `.venv`.
- [x] Playwright Chromium installed.
- [x] Mistral Large wired as the only LLM path.
- [x] Mock runtime paths removed.
- [x] OpenWA-compatible webhook normalization implemented.
- [x] Local OpenWA patched to forward self-sent WhatsApp Web commands for single-number testing.
- [x] Job/task DB model implemented with SQLite default.
- [x] Browser profile locking implemented.
- [x] Persistent profile hardening added for browser closes and laptop restarts.
- [x] OpenWA Docker config hardened with `host.docker.internal`, 120s webhook timeout, and stale Chromium session-lock cleanup.
- [x] Platform workers implemented with Browser Use prompts plus deterministic Playwright publish paths for LinkedIn, X, and Instagram.
- [x] CLI, Makefile, README, Docker Compose, `.env.example` added.
- [x] Runtime env surface trimmed to current operational knobs only.
- [x] Three Mistral keys copied from Tradeage `.env` into local `.env`.
- [x] Browser auth preflight added: persistent profile first, optional credential relogin second.
- [x] Browser Use restored with a project-local rotating Mistral adapter; deterministic Playwright is now the product publish path for verified brittle platform flows.
- [x] API health check verified locally.
- [x] API process restarted with latest code; worker user service is active.
- [x] Lint, unit test, and type check passing.
- [x] Live Mistral structured parse and full planning path verified with copied key.
- [x] Live WhatsApp webhook and reply path verified through OpenWA after restarting the session to `ready`.
- [x] Live browser publishing verified for Instagram feed/story, LinkedIn text, and X text after corrected X password.
- [x] Instagram screenshot smoke post published through deterministic Playwright flow.
- [x] Instagram Story published through mobile-web Story upload flow.
- [x] LinkedIn text smoke post published and verified in recent activity.
- [x] X text smoke post published through deterministic Playwright flow and verified in the home feed.
- [x] Actual scheduler added: future tasks stay pending until `scheduled_for` is due.
- [x] Same-day past schedule parsing fixed so `may 20 17:45` on May 20 after 17:45 fails as past instead of rolling to next year.
- [x] WhatsApp replied-to media is supported when OpenWA includes quoted media or when media is recoverable from message history.
- [x] WhatsApp media without filenames now uses MIME-derived extensions, so quoted JPEG images are stored as `.jpg` instead of `.bin`.
- [x] Instagram feed plus Story requests expand into separate Instagram platform tasks.
- [x] Explicit per-platform WhatsApp lines such as `Instagram caption - ...`, `Twitter - ...`, and `LinkedIn - ...` override LLM-generated copy.
- [x] Raw command guard normalizes `schedule` and `all 3 platforms` even if the LLM parse under-specifies them.
- [x] LinkedIn composer opening hardened to wait for the actual editable post modal and fall back to forced/DOM clicks when the visible `Start a post` pill ignores normal clicks.
- [x] LinkedIn media posting hardened to click the media editor `Next` step before the final `Post` button.
- [x] Retry state handling fixed so failed jobs are reopened to `queued`, terminal task claims are cleared, and a successful retry can roll up to `completed`.
- [x] Latest quoted-image all-platform WhatsApp job completed for X, Instagram, and LinkedIn after DB repair of a posted-but-rolled-back LinkedIn retry.
- [x] OpenWA quoted-media extraction hardened after `getQuotedMessage()` timed out on replied-to images; raw quoted media is now attempted first and Puppeteer protocol timeout is raised.
- [x] Backend now fails early when a reply-style media command such as `/post this...` arrives without any readable media, preventing text-only LinkedIn/X posts from accidental quoted-media loss.
- [x] Playwright Chromium cache restored after cache loss, and worker systemd unit now runs `playwright install chromium` as a startup preflight before accepting browser tasks.
- [x] Latest quoted-image all-platform WhatsApp retry completed for LinkedIn, X, and Instagram after restoring Playwright browsers.
- [x] Instagram feed-post-to-Story native Android worker integrated for `/feed to story` / `/feed-to-story` requests.
- [x] Instagram feed post worker now returns the latest post URL, and the worker hydrates a following feed-post Story task with that URL.
- [x] Native Instagram feed-post-to-Story path was live-verified once through the Android app using an exact post URL.
- [x] Native Android auth/open checks now require the Instagram package to be foreground, so launcher text can no longer be misclassified as authenticated UI.
- [x] Added `instagram-enter-code` CLI helper for submitting the current Instagram Android email/SMS verification code through ADB.
- [x] Instagram Story editor actions modeled as semantic task data: resize, move, card variant, text, mention, link, and music.
- [x] Deterministic command normalizer extracts Story text/link/mention/music/layout actions from WhatsApp command lines.
- [x] Instagram runtime routing now sends direct Stories with editor actions to the native Android worker; basic direct media Stories still use mobile-web Playwright.
- [x] Native Android Story editor executor added for resource-id-first text, sticker/link, music, resize, move, and card-style actions with coordinate fallbacks.
- [x] `.env` malformed copied prose removed so dotenv startup warnings are cleared.
- [x] SQLite runtime hardened with WAL/busy timeout and long browser operations no longer keep write transactions open.
- [x] WhatsApp reply sending is now best-effort, so a disconnected gateway cannot roll back a queued backend job.
- [x] Live quoted-image webhook job verified end-to-end through LLM planning and worker queueing: LinkedIn media, X media, and Instagram feed completed; Instagram feed URL hydrated into the dependent Story task.
- [x] Native Instagram email verification code entry completed; Android app is authenticated again.
- [x] Native Instagram share-sheet scanner now sweeps the horizontal carousel in both directions and confirmed `Add to story` is present after deeper scrolling.
- [x] Native Instagram `Add to story` click handling now taps the exact share-button node from the UI hierarchy and verifies the Story editor opened before continuing.
- [x] Android-native Instagram runtime fixed by installing APKPure Instagram `389.0.0.49.87` x86 split APK on ReDroid; this avoids the ARM-on-x86 SIGSEGV crash seen with earlier APKs.
- [x] Latest Android-native live test pass: auth check, direct media Story with text overlay, feed-post-to-Story, and fresh native backup all completed on the x86 Instagram build.
- [x] Android native worker now grants camera/audio/media permissions before Story UI runs and avoids profile-suggestion taps when using profile-grid latest-post fallback.
- [x] Live all-platform media smoke job `job_6fc53f881c18476b8bc1b9e076d7cb63` completed for LinkedIn media, X media, and Instagram feed.
- [x] Live Instagram direct-media Story smoke job `job_4ee18f31e469460284e487be5941134f` completed through mobile-web Story upload.
- [x] Live text-only LinkedIn/X smoke job `job_99595d2b731c4917b790817bd228df5b` completed.
- [x] Live text-only LinkedIn/X publishing completed without media assets.
- [x] Live scheduled X job stayed pending until due and completed after `scheduled_for`.
- [x] Headless browser-use auth probes passed for LinkedIn, X, and Instagram web profiles.
- [x] OpenWA API/dashboard are up, webhook is active for `message.received` and `message.sent`, and the current WhatsApp session reports `ready`.
- [x] Instagram web auth and Android-native auth are now tracked separately, so web profile success cannot hide a native verification checkpoint.
- [x] Added native auth operations: `instagram-native-auth-check`, `instagram-native-login`, `instagram-native-backup`, `instagram-native-restore`, plus API endpoints for native check/login/backup/restore.
- [x] Instagram Android verification-code helper now snapshots authenticated app data immediately after a successful code submission.
- [x] Native Instagram publish paths now auto-restore the latest good Android app-data snapshot if Instagram fails to stay foreground, before returning a native-app failure.
- [x] Tested the older pre-clear backup; it restores but reproduces Instagram's native SIGSEGV startup crash with ARM APKs, so it must not be promoted to `latest`.
- [x] Fresh x86 native backup created at `runtime/android-backups/instagram-main_brand-latest.tar.gz`; live restore drill completed. Raw restore returned `login_required`, then credential fallback relogged without OTP and wrote a fresh `latest` backup.
- [x] Android direct-media Story intent is production-usable on the x86 Instagram build: `ADD_TO_STORY` opens the Story editor, applies text overlay actions, opens the Share sheet, and completes publishing.
- [x] Native Story editor actions live-verified individually: standalone text+mention, link sticker, music selection, and feed-post Story card resize/move/card-style/text action flow.
- [x] Native latest-post fallback hardened against active profile Story viewer state and Instagram's "Leave a comment" modal; no-URL latest feed-post-to-Story live test completed.
- [x] WhatsApp webhook planner fixed for `/feed-to-story latest post to story` so existing/latest feed-post share requests create only an Instagram Story task, not an accidental feed post.
- [x] Backend queue path live-verified for existing/latest feed-post-to-Story from a WhatsApp-style webhook: `job_214efba2ec10403d8b03bdcca09183e5` completed through `/worker/run-once?platform=instagram`.
- [x] Story music can now use Instagram's first suggested track with `story music: suggested` / first-suggested wording; live native direct Story test completed.
- [x] Direct image Story text and @mention overlays are pre-rendered into a 1080x1920 Story image before upload; live text+mention and text+mention+suggested-music tests completed.
- [x] Native Story action execution is now canonicalized: media/card layout actions run before music/link/text overlays, and text+mention commands are merged into one stable rendered overlay.
- [~] Native clickable mention stickers are still best-effort; production direct image Stories use rendered @mention text for reliability. Feed-post Story card actions remain native.
- [x] Instagram Reel mode now has explicit video-asset validation, longer video upload wait, and Reel-specific success/timeout messaging on the real Instagram Create flow.

## Phase 0 - Project Setup

### 0.1 Repository Scaffolding

- [x] Create project structure.
  - [x] `apps/api`
  - [ ] `apps/whatsapp-gateway` separate service
  - [x] `workers/browser`
  - [x] `src/media_automata`
  - [x] `src/media_automata/agents`
  - [x] `src/media_automata/platforms`
  - [x] `src/media_automata/storage`
  - [x] `src/media_automata/db`
  - [x] `runtime/profiles`
  - [x] `runtime/artifacts`
  - [x] `runtime/storage`
- [x] Add root README.
- [x] Add `.env.example`.
- [x] Keep `.env.example` scoped to operational knobs: DB path, headless mode, Mistral keys, OpenWA connection, allowed WhatsApp senders, platform credentials.
- [x] Add `.gitignore` for secrets, browser profiles, artifacts, local storage, and venv.
- [x] Choose package management.
  - [x] Python: `uv`
  - [x] Node gateway skipped for now; using OpenWA adapter from Python backend.
- [x] Add formatting and linting.
  - [x] Ruff.
  - [x] Pyright.

### 0.2 Local Runtime

- [x] Add Docker Compose for optional local dependencies.
  - [x] Postgres.
  - [x] Redis.
- [x] Add simple DB migration/init command.
  - [x] SQLAlchemy `create_all` via `python -m media_automata.cli migrate`.
  - [ ] Alembic migrations.
- [x] Add local run scripts.
  - [x] `make dev`
  - [x] `make worker`
  - [x] `make migrate`
  - [x] `make test`
- [x] Create `.venv`.
- [x] Install dependencies.
- [x] Install Playwright Chromium.

## Phase 1 - Core Schemas and Data Model

### 1.1 Pydantic Schemas

- [x] Define `IncomingWhatsAppMessage`.
- [x] Define `CommandIntent`.
- [x] Define job snapshots/detail models.
- [x] Define `PlatformTaskPayload`.
- [x] Define `PlatformContent`.
- [x] Define `PlatformContentPlan`.
- [x] Define `PlatformResult`.
- [x] Define `BrowserRunStatus`.
- [x] Define `VerificationResult`.
- [x] Define `Asset`.
- [x] Define error codes.
  - [x] `LOGIN_REQUIRED`
  - [x] `CAPTCHA_OR_VERIFICATION`
  - [x] `COMPOSER_NOT_FOUND`
  - [x] `MEDIA_UPLOAD_FAILED`
  - [x] `CONTENT_REJECTED`
  - [x] `PUBLISH_BUTTON_DISABLED`
  - [x] `NETWORK_TIMEOUT`
  - [x] `UNKNOWN_UI_STATE`

### 1.2 Database Tables

- [x] Create `users`.
- [x] Create `whatsapp_contacts`.
- [x] Create `accounts`.
- [x] Create `browser_profiles`.
- [x] Create `assets`.
- [x] Create `jobs`.
- [x] Create `platform_tasks`.
- [x] Create `browser_runs`.
- [x] Create `agent_messages`.
- [x] Create `artifacts`.
- [x] Create `audit_events`.
- [x] Add primary indexes used by current queries.
  - [x] `jobs.status`
  - [x] `platform_tasks.status`
  - [x] `platform_tasks.platform`
  - [x] `browser_profiles.platform/account_key`
  - [x] `assets.sha256`
- [ ] Add foreign-key constraints.
- [ ] Add production migrations.

### 1.3 State Machines

- [x] Define job states.
  - [x] `received`
  - [x] `parsed`
  - [x] `planned`
  - [x] `queued`
  - [x] `executing`
  - [x] `completed`
  - [x] `failed`
  - [x] `cancelled`
- [x] Define platform task states.
  - [x] `pending`
  - [x] `claimed`
  - [x] `running`
  - [x] `verifying`
  - [x] `completed`
  - [x] `failed`
  - [x] `retrying`
- [x] Add transition validation.
- [x] Add audit event emission for state transitions.

## Phase 2 - WhatsApp Gateway

### 2.1 Gateway Selection

- [x] Select OpenWA as the WhatsApp gateway integration target.
- [x] Create gateway config.
  - [x] `OPENWA_BASE_URL`
  - [x] `OPENWA_API_KEY`
  - [x] `OPENWA_SESSION_ID`
- [x] Populate real `OPENWA_API_KEY`.
- [x] Run/configure OpenWA session and QR login.
  - [x] OpenWA cloned, built, and running locally through Docker Compose.
  - [x] OpenWA dashboard reachable at `http://localhost:2886`.
  - [x] OpenWA API reachable at `http://localhost:2785/api`.
  - [x] `web` session created, started, and ready.
  - [x] Local `.env` points to the generated OpenWA session ID for `web`.
  - [x] Saved WhatsApp Web session reconnects without QR after OpenWA restart.

### 2.2 Inbound Message Handling

- [x] Configure live WhatsApp session QR login in OpenWA.
  - [x] Saved OpenWA `web` session is connected and ready.
- [x] Configure OpenWA inbound webhook to backend.
  - [x] Webhook URL uses `http://host.docker.internal:8080/webhooks/whatsapp` from inside Docker.
  - [x] OpenWA webhook test endpoint returns HTTP 200 from Media Automata.
- [x] Normalize inbound messages.
  - [x] sender number
  - [x] message ID
  - [x] text body
  - [x] quoted message
  - [x] media metadata
  - [x] media payload
- [x] Store media from replied-to/quoted WhatsApp messages.
  - [x] OpenWA adapter patched to include quoted media payload when WhatsApp Web can decrypt it.
  - [x] Backend fallback can look up quoted message media from OpenWA message history when present.
- [x] Allow command-prefixed `fromMe` messages while ignoring non-command bot replies.
- [x] Store raw inbound event inside normalized message payload/job context.
- [x] Add idempotency by WhatsApp message ID.
- [x] Verify against live OpenWA payloads.
- [ ] Add webhook authenticity validation if the selected OpenWA deployment exposes a stable signature header.

### 2.3 Outbound Replies

- [x] Implement `send_text` through OpenWA.
- [x] Implement `send_image`.
- [x] Implement `send_document`.
- [x] Implement status message templates.
  - [x] job accepted/queued
  - [x] job failed
  - [x] status response
  - [x] retry response
  - [x] task started
  - [x] platform task completed
  - [x] final job completed push
  - [x] login required
- [~] Live send path is implemented and the OpenWA session is ready; pending real WhatsApp command smoke test.

### 2.4 Command Filtering

- [x] Allowlist authorized WhatsApp numbers.
- [x] Ignore messages without command prefix.
- [x] Support command prefixes.
  - [x] `/social`
  - [x] `/post`
  - [x] `/status`
  - [x] `/retry`
  - [x] `/accounts` prefix recognized
- [x] Implement `/accounts` behavior.
  - [x] WhatsApp command returns profile status, lock state, credential fallback status, and profile path.
  - [x] API endpoint `GET /accounts` returns the same operational profile state.
- [ ] Support reply-to-active-job follow-ups.

## Phase 3 - LLM Provider and Agent Foundation

### 3.1 LLM Provider Adapter

- [x] Define provider interface.
  - [x] `generate_text`
  - [x] `generate_structured`
  - [x] `judge`
  - [x] `summarize`
- [x] Implement Mistral external provider adapter.
- [x] Load Mistral API keys from environment.
- [x] Support `MISTRAL_API_KEY1-3` copied from Tradeage.
- [x] Support single `MISTRAL_API_KEYS` list for compact multi-key configuration.
- [x] Route Mistral keys by purpose:
  - [x] command/content agent uses key slot 1
  - [x] Instagram browser worker uses key slot 2
  - [x] LinkedIn/X browser workers use key slot 3
- [x] Keep Mistral model fixed to `mistral-large-latest` in code for the current scope.
- [x] Use Mistral JSON mode for structured output.
- [x] Add timeout handling via `httpx`.
- [x] Add request logging.
- [~] Add token and cost tracking.
  - [x] Token usage tracking and logging.
  - [ ] Cost calculation once current provider pricing is pinned.
- [x] Add explicit retry/backoff policy.
- [x] Rotate command/content LLM retries across configured key slots.
- [x] Live LLM parse and content-planning smoke test passed.

### 3.2 Agent Graph Setup

- [~] Create graph state model.
  - [x] `AgentPlan`.
  - [ ] Full LangGraph `StateGraph` object.
- [x] Implement graph-equivalent nodes in `SocialAgentGraph`.
  - [x] command parser node
  - [x] content strategy node
  - [x] platform content node
  - [x] platform router/task enqueue in orchestrator
  - [x] Instagram feed plus Story requests expand into separate platform content/task items.
  - [ ] result summarizer node
- [~] Implement graph edges as sequential orchestration.
  - [ ] Convert to explicit LangGraph `StateGraph`.
- [~] Persist graph state.
  - [x] parsed intent persisted on job.
  - [x] content plan persisted on job.
  - [ ] individual agent messages persisted.

### 3.3 Prompt and Output Contracts

- [x] Write command parser prompt.
- [x] Write content generation prompt.
- [x] Define JSON schemas through Pydantic.
- [x] Add schema validation for structured outputs.
- [x] Write dedicated LinkedIn content prompt.
- [x] Write dedicated X/Twitter content prompt.
- [x] Write dedicated Instagram content prompt.
- [x] Write browser verification prompt.
- [x] Add repair loop for invalid structured outputs.

### 3.4 Agent Evals

- [ ] Create eval dataset for command parsing.
- [ ] Add examples for messy WhatsApp commands.
- [x] Add examples with platform-specific instructions.
- [ ] Add examples with missing fields.
- [ ] Add examples with media attachments.
- [ ] Create eval dataset for platform routing.
- [ ] Create eval dataset for content generation.

## Phase 4 - Asset and Media Pipeline

### 4.1 Asset Ingestion

- [x] Save WhatsApp media attachments when base64 payload is present.
- [x] Save media attached to a quoted/replied-to WhatsApp message.
- [x] Store original filename and MIME type.
- [x] Derive upload-safe file extensions from MIME type when WhatsApp does not provide a filename.
- [x] Compute SHA-256.
- [x] Deduplicate identical media.
- [x] Extract image dimensions.
- [ ] Extract video duration.
- [x] Download media from URL-based payloads.

### 4.2 Asset Storage

- [x] Implement local storage driver.
- [ ] Implement S3-compatible storage driver.
- [x] Add storage URI abstraction.
- [~] Add signed/downloadable artifact URLs.
  - [x] Local artifact download endpoint.
  - [ ] Signed external URLs for object storage.

### 4.3 Media Validation

- [ ] Add platform media config.
- [ ] Validate LinkedIn images.
- [ ] Validate X/Twitter images.
- [ ] Validate Instagram feed images.
- [ ] Validate Instagram carousel count.
- [ ] Add image conversion pipeline.
- [ ] Add derived asset tracking.

## Phase 5 - Browser Runtime

### 5.1 Playwright Runtime

- [x] Install Playwright browsers.
- [x] Use Browser Use `Browser` over Playwright.
- [x] Support persistent Chromium profiles through `user_data_dir`.
- [x] Remove stale Chromium `Singleton*` profile lock files before launching a worker browser.
- [x] Remove stale Chromium `Singleton*` profile lock files before launching the OpenWA WhatsApp Web session.
- [x] Use stable first-run, default-browser-check, and password-store/keychain browser flags.
- [x] Support headful/headless via `APP_BROWSER_HEADLESS`.
- [x] Configure window size.
- [x] Pass upload file paths to Browser Use.
- [ ] Capture screenshots at standard checkpoints.
- [ ] Capture Playwright traces.
- [ ] Capture browser console logs.

### 5.2 Profile Management

- [x] Create profile registry table.
- [x] Create profile directory convention.
- [x] Add profile lock fields.
- [x] Implement acquire lock.
- [x] Implement release lock.
- [x] Implement heartbeat refresh loop.
- [x] Implement stale lock cleanup.
- [x] Add login status check per profile.
- [!] Perform real login setup for:
  - [x] `runtime/profiles/linkedin/main_brand` authenticated during live post verification.
- [x] `runtime/profiles/x/main_brand` authenticated after corrected password.
  - [x] `runtime/profiles/instagram/main_brand` authenticated after email-code checkpoint.

### 5.3 Production Login Recovery

- [x] Use persistent browser profiles as the primary auth mechanism.
- [x] Add optional credential fallback secrets:
  - [x] `LINKEDIN_EMAIL`
  - [x] `LINKEDIN_PASSWORD`
  - [x] `X_LOGIN_IDENTIFIER`
  - [x] `X_SECONDARY_IDENTIFIER`
  - [x] `X_PASSWORD`
  - [x] `INSTAGRAM_USERNAME`
  - [x] `INSTAGRAM_PASSWORD`
- [x] Add Browser Use auth preflight before every platform post.
- [x] Detect logged-in profile before publishing.
- [x] Attempt one normal credential login when profile is logged out and credentials exist.
- [x] Stop on MFA, OTP, captcha, checkpoint, suspicious login, or account lock.
- [x] Return `LOGIN_REQUIRED` or `CAPTCHA_OR_VERIFICATION` instead of posting from an uncertain auth state.
- [x] Persist profile auth status after every preflight.
- [~] Send WhatsApp manual-login alert when auth recovery stops on a challenge.
  - [x] Worker sends manual-login alert to originating chat when OpenWA credentials are configured.
  - [ ] Live alert delivery pending real WhatsApp command smoke test.
- [~] Populate real platform credentials if automatic relogin fallback is desired.
  - [x] Instagram credentials present.
  - [x] LinkedIn credentials live-verified.
- [x] X identifier, secondary email, and corrected password live-verified.
- [~] Live-verify auth preflight against LinkedIn, X, and Instagram profiles.
  - [x] Instagram credentials submitted and profile authenticated after one-time email-code checkpoint.
  - [x] Instagram Browser Use auth preflight live-verified after replacing packaged `ChatMistral`.
  - [x] LinkedIn auth live-verified and text post published.
- [x] X login reaches alternate email and password screen, then authenticates with corrected password.

### 5.3 Browser Use Integration

- [x] Add Browser Use dependency.
- [x] Create Browser Use runner around persistent profile.
- [x] Implement browser agent runner.
- [x] Add per-platform task prompts.
- [x] Add project-local Browser Use Mistral adapter.
  - [x] Uses plain Mistral JSON mode plus schema instructions.
  - [x] Rotates configured Mistral keys on retry.
  - [x] Pins Browser Use to `>=0.12.7`.
- [x] Add max step and step timeout limits.
- [x] Add upload file path exposure.
- [x] Add postificus-derived browser hardening flags.
- [~] Add custom Browser Use tools for deterministic upload/publish actions.
  - [x] Deterministic Instagram Playwright login/upload/share flow implemented and live-verified.
  - [x] Deterministic X single-post compose/publish flow promoted into the worker path.
  - [x] Deterministic LinkedIn text composer/publish flow promoted into the worker path.
  - [x] Deterministic Instagram Story mobile-web upload/share flow promoted into the worker path.
  - [ ] Expose deterministic Instagram flow as an explicit Browser Use callable tool instead of a direct worker path.
- [ ] Add detailed step logging.
- [x] Store full agent action history as artifact.

### 5.4 Optional Stagehand Integration

- [ ] Identify brittle UI actions.
- [ ] Wrap selected actions with Stagehand.
- [ ] Add `act`, `observe`, and `extract` helpers.
- [ ] Use Stagehand only inside platform worker functions.

## Phase 6 - Platform Worker Base

### 6.1 Shared Worker Interface

- [x] Define `PlatformWorker` base class.
- [x] Implement `publish_post` contract.
- [x] Implement artifact capture for task result JSON.
- [x] Implement standardized error codes.
- [ ] Implement `setup`.
- [ ] Implement `check_logged_in`.
- [x] Implement queue-level scheduled publish with `scheduled_for` due-task claiming.
- [ ] Implement `create_draft`.
- [ ] Implement `verify_result`.

### 6.2 Task Runner

- [x] Claim pending task.
  - [x] Claim only tasks with no schedule or with `scheduled_for <= now`.
- [x] Acquire browser profile lock.
- [x] Start browser run record.
- [x] Execute platform worker.
- [x] Save result artifact.
- [x] Complete task.
- [x] Release lock.
- [x] Refresh job rollup.
- [~] Send per-task WhatsApp status update.
  - [x] Worker sends task started/completed/final status when OpenWA is configured.
  - [ ] Live delivery pending real WhatsApp command smoke test.
- [ ] Run tasks through Redis queue.

### 6.3 Retry Logic

- [~] Implement basic retry.
  - [x] `/retry job_<id>`.
  - [x] `/retry job_<id> x`.
  - [x] reset failed tasks to pending.
- [x] Classify retryable errors.
- [x] Classify non-retryable errors.
- [x] Add exponential backoff.
- [x] Preserve previous run artifacts.

## Phase 7 - LinkedIn Worker

### 7.1 Login and Profile Setup

- [x] Create LinkedIn browser profile directory when task is created.
- [x] Implement login check at LinkedIn feed.
- [x] Save login-required screenshot during live probes.
- [ ] Add account metadata.
  - [ ] personal profile
  - [ ] company page
  - [ ] default target
- [x] LinkedIn profile authenticated through credential fallback.

### 7.2 Composer Flow

- [x] Browser Use prompt can navigate, authenticate, open composer, and click the exact Post button.
- [x] Add deterministic Playwright selectors for common composer flow.
  - [x] Deterministic visible-field login selectors and recent-activity verification used in live smoke test.
  - [x] Promote deterministic LinkedIn composer helper into the worker for repeatable recovery.
- [~] Upload image media via deterministic tool.
  - [x] Code path implemented.
  - [!] Live LinkedIn image-post test still pending.
- [x] Verify completion.
- [ ] Extract post URL.
- [x] Manual live test with logged-in profile.

### 7.3 Browser Use Recovery

- [x] Add Browser Use instruction for finding composer.
- [x] Add Browser Use instruction for publish completion.
- [x] Add Browser Use instruction for closing popups.
- [ ] Store successful UI action path as memory.

### 7.4 LinkedIn Tests

- [x] Unit test content payload validation.
- [ ] Browser task state transition test.
- [x] Manual live test with text-only post.
- [!] Manual live test with image post.

## Phase 8 - X/Twitter Worker

### 8.1 Login and Profile Setup

- [x] Create X browser profile directory when task is created.
- [x] Implement login check at `https://x.com/home`.
- [x] Save login-required screenshot/artifacts.
- [ ] Add profile config.
- [x] X profile authenticated after corrected password and alternate email verification.

### 8.2 Single Post Flow

- [~] Browser Use prompt can navigate to `https://x.com/compose/post`, authenticate, and fill the composer.
  - Browser Use live run filled the post but mis-clicked the thread controls; prompt tightened to avoid "Add post" and "Post all" for single posts.
- [x] Add deterministic Playwright selectors for compose textbox/button.
  - Live-verified with `tweetTextarea_0` plus `tweetButton`/`tweetButtonInline` selectors.
  - [x] Deterministic single-post helper promoted into the worker for WhatsApp-triggered tasks.
- [~] Upload image media via deterministic tool.
  - [x] Code path implemented.
  - [!] Live X image-post test still pending.
- [x] Verify completion.
- [ ] Extract post URL when possible.
- [x] Manual live test with logged-in profile.

### 8.3 Thread Flow

- [x] Split generated content into thread posts.
- [x] Validate length per post.
- [ ] Add another post in composer.
- [ ] Fill each thread item.
- [ ] Upload media to correct item if needed.
- [ ] Publish thread.
- [ ] Verify completion.

### 8.4 Reference-Derived Selectors

- [ ] Test `[data-testid="tweetTextarea_0"]`.
- [ ] Test `[data-testid="tweetButton"]`.
- [ ] Test file input handling.
- [x] Add fallback Browser Use flow.

### 8.5 X Tests

- [x] Unit test thread splitting.
- [x] Unit test character limits.
- [!] Manual live test with text-only post.
- [!] Manual live test with image post.
- [ ] Manual live test with thread.

## Phase 9 - Instagram Worker

### 9.1 Login and Profile Setup

- [x] Create Instagram browser profile directory when task is created.
- [x] Implement login check at Instagram home/profile.
- [~] Save login-required screenshot.
- [x] Add profile config.
- [x] Manually log in to Instagram profile.

### 9.2 Feed Post Flow

- [~] Browser Use prompt can create/publish a feed post.
- [x] Add deterministic Playwright file chooser helper.
- [x] Handle crop/ratio screen in deterministic helper.
- [x] Handle edit/filter screen in deterministic helper.
- [x] Verify "post shared" or equivalent in deterministic helper.
- [x] Promote deterministic feed post helper into the worker for WhatsApp-triggered tasks.
- [x] Capture final shared screenshot.
- [x] Manual live test with logged-in profile.

### 9.3 Carousel Flow

- [ ] Validate image count.
- [ ] Upload multiple files.
- [ ] Handle carousel ordering.
- [ ] Fill caption.
- [ ] Publish.
- [ ] Verify completion.

### 9.4 Story Flow

- [x] Mobile-web Story upload path implemented with iPhone viewport.
- [x] Story helper tries "Your story" controls and hidden file inputs.
- [x] Story share confirmation and screenshots captured.
- [x] Deterministic Story helper promoted into the worker for WhatsApp-triggered tasks.
- [x] Manual live test with logged-in profile.

### 9.5 Reels Flow

- [ ] Validate video media.
- [ ] Upload reel.
- [ ] Fill caption.
- [ ] Select cover if needed.
- [ ] Publish.
- [ ] Verify completion.

### 9.6 Instagram Tests

- [ ] Unit test media validation.
- [!] Manual live test with single image.
- [ ] Manual live test with carousel.
- [ ] Manual live test with reel if in scope.

## Phase 10 - Orchestration and Job Execution

### 10.1 MVP Queue

- [x] DB-backed pending task queue.
- [x] Enqueue platform tasks.
- [x] Store `scheduled_for` on jobs and platform tasks.
- [x] Do not claim scheduled tasks until the due time.
- [x] Run worker process.
- [x] Add task timeout through Browser Use step timeout.
- [x] Add task heartbeat.
  - [x] heartbeat timestamp set on claim.
  - [x] periodic browser profile lock heartbeat update.
  - [x] periodic platform task heartbeat update.
- [~] Add retry queue.
  - [x] failed task reset to pending.
  - [ ] backoff and retry scheduling.
- [ ] Redis queue.

### 10.2 Temporal Upgrade

- [ ] Define `SocialPublishWorkflow`.
- [ ] Define activities.
- [ ] Add workflow search attributes.
- [ ] Add workflow retry policies.
- [ ] Add cancellation support.

### 10.3 Parallel Platform Execution

- [ ] Execute independent platform tasks in parallel.
- [x] Prevent same-profile concurrent use.
- [x] Aggregate results through job rollup.
- [x] Support partial success/failure state.

## Phase 11 - WhatsApp Result UX

### 11.1 Status Messages

- [x] Build job accepted message.
- [x] Build task started message.
- [x] Build task completed message.
- [x] Build final job completed message.
- [x] Build failure message.
- [x] Build retry result message.

### 11.2 Status Command

- [x] Implement `/status <job_id>`.
- [x] Return job state.
- [x] Return per-platform state.
- [x] Return latest artifact links or IDs.

### 11.3 Retry Command

- [x] Implement `/retry <job_id>`.
- [x] Implement `/retry <job_id> x`.
- [x] Re-queue failed platform tasks.
- [ ] Create distinct retry task attempts linked to original task.

### 11.4 Follow-Up Edits

- [ ] Support editing last active job.
- [ ] Parse messages like `edit x: make it shorter`.
- [ ] Regenerate platform content.
- [ ] Re-run selected platform task.

## Phase 12 - Observability and Artifacts

### 12.1 Structured Logging

- [x] Add request ID.
- [x] Add job ID in task records.
- [x] Add platform task ID in task records.
- [x] Add browser run ID.
- [x] Add platform/account fields.
- [x] Log state transitions as audit events.

### 12.2 Artifact Capture

- [x] Save platform result JSON artifact.
- [x] Save screenshots at standard checkpoints for deterministic platform workers.
- [ ] Save Playwright trace.
- [ ] Save console logs.
- [x] Save browser agent action history.
- [x] Save final verification evidence for current live smoke jobs.

### 12.3 Artifact Viewer

- [x] Create simple local artifact index.
- [x] Link artifacts from job status.
- [x] Add trace download path.
- [ ] Add screenshot preview path.

## Phase 13 - Admin Dashboard

### 13.1 Job Dashboard

- [x] List jobs.
- [x] Filter by status.
- [x] Filter by platform.
- [x] View raw WhatsApp command.
- [x] View parsed plan.
- [x] View generated platform content.
- [x] View platform task results.

### 13.2 Browser Profile Dashboard

- [x] List profiles.
- [x] Show login status.
- [x] Show lock status.
- [x] Start login check.
- [x] Open profile setup instructions.

### 13.3 Artifact Dashboard

- [ ] View screenshots.
- [ ] Download traces.
- [ ] View agent action timeline.
- [ ] View errors.

## Phase 14 - Security and Secrets

### 14.1 Secrets

- [x] Store Mistral API keys in environment.
- [x] Store WhatsApp gateway API key in environment.
- [x] Keep fixed project defaults out of `.env`.
- [x] Keep `.env` ignored.
- [x] Never commit browser profiles.
- [x] Never commit storage state.
- [x] Never commit runtime artifacts.
- [ ] Integrate secret manager for production.

### 14.2 Authorization

- [x] Add WhatsApp sender allowlist.
- [ ] Add user roles beyond current default operator.
- [ ] Add admin-only commands.
- [x] Add audit logs for commands/state changes.

### 14.3 Operational Boundaries

- [ ] Add max posts per job.
- [x] Add max concurrent jobs.
- [x] Add max media size.
- [x] Add per-platform execution timeout.
- [x] Add manual kill switch.

## Phase 15 - Testing Strategy

### 15.1 Unit Tests

- [x] Schemas.
- [ ] Command parsing fixtures.
- [x] Platform content validation.
- [x] Media validation.
- [x] State transitions.
- [x] Retry classification.

### 15.2 Integration Tests

- [x] WhatsApp webhook normalization.
- [ ] Job creation with recorded Mistral fixture.
- [ ] Agent graph execution with recorded Mistral fixture.
- [x] Queue worker task claiming.
- [x] Artifact storage.
- [x] Platform-specific instruction override tests.

### 15.3 Browser Tests

- [ ] Local HTML composer tests.
- [ ] Playwright smoke tests with local test pages.
- [!] Live profile login checks.
- [!] Manual live publish tests per platform.

### 15.4 Agent Evals

- [ ] Command parser evals.
- [ ] Content generation evals.
- [ ] Platform routing evals.
- [ ] Browser verification evals.

## Phase 16 - Deployment

### 16.1 MVP Deployment

- [x] Single-machine local deployment path documented.
- [x] Backend can run.
- [x] OpenWA gateway running locally.
- [x] Browser worker can run.
- [x] ReDroid runtime has a systemd user service for production startup.
- [x] Production runbook added at `deploy/production.md`.
- [x] User systemd installer added for API, worker, ReDroid, monitor, and optional deep native checks.
- [ ] Redis-backed worker.
- [ ] Postgres-backed deployment verified.
- [x] Persistent browser profile volume path configured.
- [x] Artifact volume path configured.

### 16.2 Browser Runtime Deployment

- [x] Install Chromium dependencies via Playwright.
- [x] Configure headful/headless mode.
- [x] Configure profile volume.
- [x] Configure artifact volume.
- [x] Add process supervisor.
- [x] Add restart policy.

### 16.3 Health Checks

- [x] API health check.
- [x] Deployment health endpoint added at `GET /health/deployment`.
  - [x] Live lightweight deployment check returns `ok`.
  - [x] Live deep deployment check returns `ok` with Instagram native auth `authenticated`.
- [x] DB init check.
- [ ] Redis health check.
- [x] WhatsApp gateway health check.
  - [x] `GET /whatsapp/session` checks configured OpenWA session.
  - [x] Media Automata can read the configured OpenWA `web` session.
  - [x] `POST /whatsapp/session/recover` and `monitor-once` can start/recover the configured OpenWA session.
- [x] Browser worker empty-queue check.
- [x] Queue health check reports due, scheduled, active, and stale active platform tasks.
- [x] Runtime path health check validates storage, artifacts, and browser profile directories are writable.
- [x] Android backup health check validates `runtime/android-backups/instagram-main_brand-latest.tar.gz`.
- [x] `media-automata-monitor.timer` is enabled, has run successfully, and will run every two minutes.
- [x] `media-automata-deep-check.timer` is enabled for hourly Instagram native runtime/auth checks.
- [~] Platform login health checks.
  - [x] `POST /accounts/{platform}/login-check` runs auth preflight and stores profile status.
  - [x] Optional deep deployment check runs Instagram native runtime/auth check and records native status.
  - [!] Live checks require social profile login and/or platform credentials.

## Phase 17 - MVP Delivery Checklist

- [~] One WhatsApp user can send `/social publish`.
  - [x] OpenWA session is ready.
  - [x] OpenWA webhook delivers to the backend with HTTP 200.
  - [ ] Pending live command smoke test from the connected WhatsApp account.
- [x] Backend receives and stores command.
- [x] Agent parses command into structured job through Mistral.
  - Live smoke test passed with LinkedIn/X/Instagram command.
- [x] Agent generates LinkedIn, X, and Instagram content through Mistral.
  - Live smoke test passed through full planning path.
- [x] Assets from WhatsApp are stored when base64 media is supplied.
- [x] Assets from quoted/replied-to WhatsApp media are stored when OpenWA supplies or can recover the media.
- [x] Platform tasks are created.
- [x] LinkedIn worker can publish text post.
  - Deterministic Playwright worker path implemented; earlier live smoke post verified in recent activity.
- [x] X worker can publish text post.
  - Deterministic Playwright path live-published and verified in the home feed after corrected password.
- [x] Instagram worker can publish image post.
  - Browser Use auth preflight live-verified.
  - Deterministic Playwright feed post path live-verified and promoted into worker path.
- [x] Instagram worker can publish Story.
  - Deterministic mobile-web Story upload path live-verified and promoted into worker path.
- [x] Schedule intent queues future jobs without immediate worker claim.
- [x] Instagram feed plus Story command creates two Instagram tasks.
  - [x] Duplicate feed/story expansions from extra LLM Instagram content are de-duped before task creation.
- [x] Instagram Story tasks differentiate direct media Story uploads from feed-post-to-Story shares.
  - [!] Headless web test shows Instagram web exposes no feed-post share-to-Story control for the latest post; direct Story upload works.
  - [!] Headful web inspection shows the same limitation: latest post exposes like/comment/save only, not add/share-to-Story.
  - [!] Mobile and desktop web `More options` menus also lack share/add-to-Story; mobile has Delete/Hide likes/Turn off commenting/About/Cancel, desktop adds Edit/Go to post.
  - [x] Explicit `/direct story`, `/feed to story`, and `/feed-to-story` keywords are recognized.
  - [x] Native Android worker route added for `/feed to story` / `instagram_story_source=feed_post`.
  - [x] ReDroid Docker service/helper script added for server-side Android runtime.
  - [x] Feed post result URL is propagated into the follow-up feed-post-to-Story task.
  - [x] Story editor action model implemented for resize/move/card variant/text/mention/link/music.
  - [x] Android native Story editor executor applies semantic actions before publish.
  - [x] Direct media Stories with editor actions route to Android native; direct media Stories without editor actions remain on Playwright.
  - [x] Native Instagram app installed inside the Android runtime.
  - [x] Native Instagram app replaced with APKPure `389.0.0.49.87` x86 split APK for ReDroid; ARM APKs caused native SIGSEGV crashes on the x86 runtime.
  - [x] Native Instagram app login re-verified after app reinstall/email challenge.
  - [x] Live native feed-post-to-Story publish verified through Android app automation using an exact post URL.
  - [x] Live native direct-media Story publish verified through `ADD_TO_STORY`, Story editor text overlay, Share sheet, and final completion detection.
  - [x] Deep native share-sheet scan confirmed `Add to story` is present behind the horizontal carousel for the tested post/account state.
  - [x] `Add to story` button selection now prefers exact `content-desc` + `com.instagram.android:id/button` bounds and rejects false-positive label clicks unless the Story editor actually opens.
  - [x] Fully unattended native reruns pass for direct Story and feed-post-to-Story after the x86 APK fix.
  - [x] Restore drill from the fresh x86 backup completed with credential fallback recovery and a fresh latest backup snapshot.
  - [x] Existing/latest feed-post-to-Story requests are modeled as Story-only jobs and verified through the WhatsApp webhook plus backend worker path.
- [x] Explicit platform caption overrides accept `Platform caption text`, `Platform caption - text`, and `Platform - text`.
- [x] Text-only LinkedIn and X commands are allowed even when wording says "post this" without media.
- [x] LinkedIn media posts fill/re-fill post text after LinkedIn's media editor transition so captions are not wiped.
- [x] Instagram Story auth check prefers authenticated mobile feed controls over generic login text.
- [x] Instagram Story publish confirmation waits longer and treats an active upload with no visible error as submitted.
- [x] Browser result artifacts are saved.
- [~] WhatsApp receives status replies.
  - Code implemented and OpenWA session ready; pending real WhatsApp command smoke test.
- [x] Failed platform task can be retried.

## Phase 18 - Future Enhancements

- [ ] Multi-account support.
- [x] Scheduled publishing.
- [ ] Calendar view.
- [ ] Content templates.
- [ ] Brand voice memory.
- [ ] Competitor/research ingestion.
- [ ] Auto-generate image variants.
- [ ] Reels and video workflows.
- [ ] LinkedIn document posts.
- [ ] X threads with media.
- [x] Instagram stories.
  - [x] Mobile-web Story entrypoint and file inputs detected in live profile.
  - [x] Deterministic Story worker path added for `mode="story"`.
  - [x] Feed plus Story command expansion creates separate Instagram tasks.
  - [x] Live Story publish test.
  - [x] Native Android automation path added for feed-post-to-Story, which Instagram web does not expose.
  - [x] Native Android runtime operational test on deployment target.
    - ReDroid, ADB, x86 Instagram `389.0.0.49.87`, native auth check, direct Story, feed-post-to-Story, and native backup were verified locally.
    - The root cause of repeated startup/upload crashes was ARM Instagram APKs running through translation on x86 ReDroid. The x86 split APK is now the required ReDroid production build.
    - Fresh native backup succeeds after the x86 fix and writes `runtime/android-backups/instagram-main_brand-latest.tar.gz`.
    - Feed-post-to-Story finds the real `Add to story` share-sheet button, opens the native Story editor, presses the final Share flow, and returns success after the post-publish `Also share to` sheet.
    - Direct-media Story through `ADD_TO_STORY` opens the native Story editor, applies text overlay actions, opens the Share sheet, and returns success after reaching the home feed.
    - Web and native auth states are now separate; native auth check/backup/restore commands and API endpoints are implemented.
    - Worker publish paths auto-restore `runtime/android-backups/instagram-main_brand-latest.tar.gz` when Instagram fails to remain foreground. Remaining hardening item: live-test restore from the fresh x86 backup after a controlled app-data reset.
- [ ] Browser action memory.
- [ ] Platform UI change detection.
- [ ] Team approval workflows.
- [ ] Analytics scraping.

## Phase 19 - PointBlank Infra Deployment

- [x] Inspect `pointblank-club/infra` deployment layout.
  - [x] Confirmed ArgoCD app-of-apps watches `argocd/apps`.
  - [x] Added `media-automata` ArgoCD Application.
  - [x] Split OpenWA into its own reusable ArgoCD Application.
  - [x] Updated app images to the `ghcr.io/unichronic/*` namespace.
  - [x] Normalized OpenWA/media manifests to existing infra style: app-of-apps entries, app folders under `argocd/<app>`, simple `app:` selectors, `ClusterIP` services with TCP ports, and `imagePullPolicy: Always`.
- [x] Add Kubernetes manifests for the production stack.
  - [x] Namespace, ConfigMaps, PVCs, Services, API/worker Deployment.
  - [x] Shared OpenWA Deployment using the patched OpenWA image in the standalone `openwa` namespace.
  - [x] `media-automata` points to `http://openwa-api.openwa.svc.cluster.local:2785/api`.
  - [x] ReDroid Deployment with privileged binder setup and pinned image digest.
  - [x] Monitor and deep-check CronJobs.
- [x] Add deployment handoff docs.
  - [x] Image build/push commands.
  - [x] Private secret creation flow that keeps credentials out of Git.
  - [x] Persistent state restore map for app runtime, shared OpenWA, and ReDroid.
- [x] Add production Docker image for `media_automata`.
  - [x] Includes Playwright Chromium and Android ADB tooling.
  - [x] Local image build succeeded and is tagged as `ghcr.io/unichronic/media-automata:v1`.
- [x] Rebuild patched OpenWA image from the current local OpenWA tree.
  - [x] Local image build succeeded and is tagged as `ghcr.io/unichronic/openwa:v1`.
  - [x] OpenWA patch commit was rebased onto `unichronic/OpenWA` main and pushed.
- [x] Validate deployment artifacts locally.
  - [x] `media-automata` container CLI smoke test passed.
  - [x] API import smoke test passed.
  - [x] OpenWA image dist smoke test passed.
  - [x] Kubernetes manifests dry-run successfully.
  - [x] YAML parse check covered the ArgoCD Application and app manifests.
- [ ] Push production images to GHCR.
  - [!] Blocked locally because Docker has no configured GHCR auth.
- [ ] Create real production Kubernetes secrets.
  - [!] Must be applied from a private source, not committed to the infra repo.
- [ ] Restore production persistent state into PVCs.
  - [!] Required for WhatsApp session, browser profiles, database, media/artifacts, and Android/Instagram native state.
- [ ] Commit and push infra manifests to `pointblank-club/infra` main.
  - [!] ArgoCD will only deploy after the infra repo receives the new manifests.
- [ ] Run post-sync production verification.
  - [ ] `GET /health/deployment?recover_openwa=true&deep_instagram=true`.
  - [ ] Real WhatsApp `/post` group command smoke test.
