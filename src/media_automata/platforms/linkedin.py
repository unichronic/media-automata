from __future__ import annotations

from media_automata.platforms.base import WorkerContext
from media_automata.platforms.browser_use_worker import BrowserUsePlatformWorker, content_text, media_paths
from media_automata.platforms.playwright_helpers import body_text, click_first, fill_textbox, first_visible, screenshot
from media_automata.platforms.profile import persistent_browser_args, prepare_persistent_profile
from media_automata.schemas import ErrorCode, PlatformResult, PlatformTaskPayload


class LinkedInWorker(BrowserUsePlatformWorker):
    allowed_domains = ["*.linkedin.com", "linkedin.com"]
    mistral_purpose = "browser:linkedin"
    auth_start_url = "https://www.linkedin.com/feed/"
    auth_success_description = (
        "the LinkedIn feed, Start a post composer, profile menu, or authenticated navigation is visible"
    )
    auth_login_description = "LinkedIn sign in fields, join/sign-in buttons, or a login challenge is visible"

    async def publish_post(
        self,
        payload: PlatformTaskPayload,
        context: WorkerContext,
        asset_lookup: dict[str, str],
    ) -> PlatformResult:
        return await self._publish_with_playwright(payload, context, asset_lookup)

    async def _publish_with_playwright(
        self,
        payload: PlatformTaskPayload,
        context: WorkerContext,
        asset_lookup: dict[str, str],
    ) -> PlatformResult:
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:  # pragma: no cover - exercised only when optional dependency is absent
            return PlatformResult(
                platform=payload.platform,
                status="failed",
                message=f"Playwright is not installed: {exc}",
                error_code=ErrorCode.INTERNAL_ERROR,
            )

        text = content_text(payload)
        files = media_paths(payload, context, asset_lookup)
        screenshots: list[str] = []
        credentials = context.settings.platform_login_credentials(str(payload.platform))

        async def classify(page) -> str:
            page_text = (await body_text(page)).lower()
            url = page.url.lower()
            authenticated_controls = await page.locator(
                ".share-box-feed-entry__trigger, button:has-text('Start a post')"
            ).count()
            if authenticated_controls:
                return "authenticated"
            challenge_markers = [
                "security check",
                "captcha",
                "verification code",
                "enter the code",
                "enter your code",
                "enter the pin",
                "enter your pin",
                "two-step verification",
                "confirm your identity",
                "we need to verify",
                "unusual activity",
            ]
            if "checkpoint" in url or "challenge" in url or any(marker in page_text for marker in challenge_markers):
                return "challenge"
            login_field_count = await page.locator("#username, input[name='session_key']").count()
            if "login" in url or login_field_count:
                return "login"
            if any(marker in page_text for marker in ["start a post", "feed", "messaging", "notifications", "profile"]):
                return "authenticated"
            return "unknown"

        async def login_once(page) -> str:
            if not credentials:
                return "login_required"
            user = await first_visible(
                page,
                ["#username", 'input[name="session_key"]', 'input[autocomplete="username"]', 'input[type="email"]'],
                timeout=9000,
            )
            password = await first_visible(
                page,
                ["#password", 'input[name="session_password"]', 'input[type="password"]'],
                timeout=9000,
            )
            if user is None or password is None:
                return "login_required"
            await fill_textbox(page, user, credentials.identifier)
            await fill_textbox(page, password, credentials.password)
            await screenshot(page, context, payload, "login-filled", screenshots)
            if not await click_first(
                [
                    ("sign-in-role", lambda: page.get_by_role("button", name="Sign in")),
                    ("sign-in-button", lambda: page.locator('button[type="submit"]')),
                ],
                timeout=5000,
            ):
                await password.press("Enter")
            await page.wait_for_timeout(9000)
            return await classify(page)

        async def ensure_authenticated(page) -> str:
            await page.goto(self.auth_start_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3500)
            state = await classify(page)
            if state == "login":
                state = await login_once(page)
            return state

        async def dismiss_popups(page) -> None:
            for _ in range(3):
                clicked = await click_first(
                    [
                        ("dismiss", lambda: page.get_by_role("button", name="Dismiss")),
                        ("skip", lambda: page.get_by_role("button", name="Skip")),
                        ("not-now", lambda: page.get_by_text("Not now", exact=True)),
                        ("close", lambda: page.locator('button[aria-label="Dismiss"]')),
                    ],
                    timeout=2500,
                )
                if not clicked:
                    return
                await page.wait_for_timeout(1200)

        async def find_post_editor(page, timeout: int = 4000):
            return await first_visible(
                page,
                [
                    ".ql-editor[contenteditable='true']",
                    ".share-creation-state__text-editor .ql-editor",
                    'div[role="textbox"][contenteditable="true"]',
                    'div[contenteditable="true"][aria-label*="text" i]',
                    'div[contenteditable="true"]',
                ],
                timeout=timeout,
            )

        async def open_composer(page):
            existing_editor = await find_post_editor(page, timeout=1200)
            if existing_editor is not None:
                return existing_editor

            candidates = [
                ".share-box-feed-entry__trigger",
                "button.share-box-feed-entry__trigger",
                "button:has-text('Start a post')",
                "[role='button']:has-text('Start a post')",
                "[aria-label*='Start a post' i]",
            ]
            for selector in candidates:
                locator = page.locator(selector).first
                try:
                    await locator.wait_for(state="visible", timeout=5000)
                except Exception:
                    continue

                for mode in ("normal", "force", "closest"):
                    try:
                        if mode == "normal":
                            await locator.click(timeout=5000)
                        elif mode == "force":
                            await locator.click(timeout=5000, force=True)
                        else:
                            await locator.evaluate(
                                """node => {
                                    const clickable = node.closest('button,[role="button"],a') || node;
                                    clickable.click();
                                }"""
                            )
                        await page.wait_for_timeout(1800)
                        editor = await find_post_editor(page, timeout=5000)
                        if editor is not None:
                            return editor
                    except Exception:
                        continue
            return None

        async def upload_media(page) -> bool:
            if not files:
                return True
            candidates = [
                ("add-media", lambda: page.locator('button[aria-label*="Add media" i]')),
                ("photo", lambda: page.locator('button[aria-label*="Photo" i]')),
                ("media-text", lambda: page.get_by_text("Media", exact=True)),
            ]

            for _, candidate in candidates:
                locator = candidate().first
                try:
                    await locator.wait_for(state="visible", timeout=4000)
                    async with page.expect_file_chooser(timeout=5000) as file_chooser_info:
                        await locator.click(timeout=4000)
                    file_chooser = await file_chooser_info.value
                    await file_chooser.set_files(files)
                    await page.wait_for_timeout(4000)
                    page_text = (await body_text(page)).lower()
                    return "not supported" not in page_text and "couldn't be uploaded" not in page_text
                except Exception:
                    continue

            try:
                await page.locator('input[type="file"]').first.set_input_files(files, timeout=10000)
                await page.wait_for_timeout(4000)
                page_text = (await body_text(page)).lower()
                return "not supported" not in page_text and "couldn't be uploaded" not in page_text
            except Exception:
                return False

        async with async_playwright() as playwright:
            prepare_persistent_profile(context.profile_path)
            browser = await playwright.chromium.launch_persistent_context(
                str(context.profile_path),
                headless=context.settings.browser_headless,
                viewport={"width": 1400, "height": 1000},
                args=persistent_browser_args(),
            )
            page = browser.pages[0] if browser.pages else await browser.new_page()
            try:
                auth_state = await ensure_authenticated(page)
                await screenshot(page, context, payload, "auth-state", screenshots)
                if auth_state == "challenge":
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="LinkedIn requires manual verification before posting.",
                        error_code=ErrorCode.CAPTCHA_OR_VERIFICATION,
                        raw={"auth_status": "challenge_required", "screenshots": screenshots},
                    )
                if auth_state != "authenticated":
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="LinkedIn login is required before posting.",
                        error_code=ErrorCode.LOGIN_REQUIRED,
                        raw={"auth_status": "login_required", "screenshots": screenshots},
                    )
                await dismiss_popups(page)

                editor = await open_composer(page)
                if editor is None:
                    await screenshot(page, context, payload, "composer-button-not-found", screenshots)
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="LinkedIn Start a post control was not found.",
                        error_code=ErrorCode.COMPOSER_NOT_FOUND,
                        raw={"auth_status": "authenticated", "screenshots": screenshots},
                    )
                if not files:
                    await fill_textbox(page, editor, text)
                    await screenshot(page, context, payload, "text-filled", screenshots)

                if not await upload_media(page):
                    await screenshot(page, context, payload, "media-upload-failed", screenshots)
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="LinkedIn media upload control did not accept the files.",
                        error_code=ErrorCode.MEDIA_UPLOAD_FAILED,
                        raw={"auth_status": "authenticated", "screenshots": screenshots},
                    )
                if files:
                    await click_first(
                        [
                            ("media-editor-next", lambda: page.get_by_role("button", name="Next")),
                            ("media-editor-next-text", lambda: page.get_by_text("Next", exact=True)),
                        ],
                        timeout=7000,
                    )
                    await page.wait_for_timeout(2500)
                    await screenshot(page, context, payload, "media-next", screenshots)
                    if text.strip():
                        editor = await find_post_editor(page, timeout=7000)
                        if editor is None:
                            await screenshot(page, context, payload, "editor-not-found-after-media", screenshots)
                            return PlatformResult(
                                platform=payload.platform,
                                status="failed",
                                message="LinkedIn post text editor was not found after media upload.",
                                error_code=ErrorCode.COMPOSER_NOT_FOUND,
                                raw={"auth_status": "authenticated", "screenshots": screenshots},
                            )
                        await fill_textbox(page, editor, text)
                        await screenshot(page, context, payload, "text-filled", screenshots)

                if not await click_first(
                    [
                        ("post-role", lambda: page.get_by_role("button", name="Post")),
                        ("primary-action", lambda: page.locator("button.share-actions__primary-action")),
                    ],
                    timeout=10000,
                ):
                    await screenshot(page, context, payload, "post-button-not-found", screenshots)
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="LinkedIn Post button was not found or was disabled.",
                        error_code=ErrorCode.PUBLISH_BUTTON_DISABLED,
                        raw={"auth_status": "authenticated", "screenshots": screenshots},
                    )

                await page.wait_for_timeout(8000)
                await screenshot(page, context, payload, "post-submitted", screenshots)
                page_text = await body_text(page)
                if text[:40] in page_text:
                    return PlatformResult(
                        platform=payload.platform,
                        status="success",
                        message="LinkedIn post published.",
                        raw={"auth_status": "authenticated", "screenshots": screenshots},
                    )
                error_markers = ["couldn't post", "try again", "something went wrong"]
                if any(marker in page_text.lower() for marker in error_markers):
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="LinkedIn reported an error after submitting the post.",
                        error_code=ErrorCode.UNKNOWN_UI_STATE,
                        raw={"auth_status": "authenticated", "screenshots": screenshots},
                    )
                return PlatformResult(
                    platform=payload.platform,
                    status="success",
                    message="LinkedIn post submitted; direct feed confirmation was not visible yet.",
                    raw={"auth_status": "authenticated", "screenshots": screenshots},
                )
            finally:
                await browser.close()

    def task_prompt(self, payload: PlatformTaskPayload, context: WorkerContext, asset_lookup: dict[str, str]) -> str:
        media = media_paths(payload, context, asset_lookup)
        media_line = f"Upload these media files: {media}" if media else "No media upload is required."
        return f"""
Go to https://www.linkedin.com/feed/ using the current browser session.
Create and publish a new post for account/target: {payload.account}.

Post text:
{content_text(payload)}

{media_line}

Open the "Start a post" composer. Enter the post text exactly once; if the text is already present, do not type it
again. Click only the exact "Post" button to publish. Do not click "Schedule post".
After publishing, return any visible post URL, confirmation text, or recent-activity evidence.
If cookie banners, onboarding prompts, or non-critical popups block the composer, close them.
If the UI is uncertain or asks for verification, stop and report the blocker instead of publishing.
"""
