from __future__ import annotations

from media_automata.platforms.base import WorkerContext
from media_automata.platforms.browser_use_worker import BrowserUsePlatformWorker, content_text, media_paths
from media_automata.platforms.playwright_helpers import body_text, click_first, fill_textbox, first_visible, screenshot
from media_automata.platforms.profile import persistent_browser_args, prepare_persistent_profile
from media_automata.schemas import ErrorCode, PlatformResult, PlatformTaskPayload

X_AUTH_CONTROL_SELECTORS = [
    '[data-testid="SideNav_NewTweet_Button"]',
    '[aria-label="Home timeline"]',
    'a[href="/home"]',
    '[data-testid="AppTabBar_Home_Link"]',
    '[data-testid="SideNav_AccountSwitcher_Button"]',
]
X_LOGIN_INPUT_SELECTORS = [
    'input[name="password"]',
    'input[name="text"]',
    'input[autocomplete="username"]',
]
X_CHALLENGE_MARKERS = ("verification", "captcha", "suspicious", "enter the code")
X_AUTH_MARKERS = ("what’s happening?", "what's happening?", "your home timeline", "post", "messages", "notifications")


def classify_x_auth_state(
    text: str,
    url: str,
    *,
    login_input_visible: bool = False,
    authenticated_control_visible: bool = False,
) -> str:
    page_text = text.lower()
    current_url = url.lower()
    if any(marker in page_text for marker in X_CHALLENGE_MARKERS):
        return "challenge"
    if authenticated_control_visible:
        return "authenticated"
    if "login" in current_url or "i/flow/login" in current_url or login_input_visible:
        return "login"
    if any(marker in page_text for marker in X_AUTH_MARKERS):
        return "authenticated"
    if "x.com/home" in current_url or "twitter.com/home" in current_url:
        return "loading"
    return "unknown"


class XWorker(BrowserUsePlatformWorker):
    allowed_domains = ["x.com", "*.x.com", "twitter.com", "*.twitter.com"]
    mistral_purpose = "browser:x"
    auth_start_url = "https://x.com/home"
    auth_success_description = "the X home timeline, left navigation, account switcher, or post composer is visible"
    auth_login_description = "X sign in fields, password screen, or account verification prompt is visible"

    async def publish_post(
        self,
        payload: PlatformTaskPayload,
        context: WorkerContext,
        asset_lookup: dict[str, str],
    ) -> PlatformResult:
        if payload.content.mode == "thread":
            return await super().publish_post(payload, context, asset_lookup)
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

        async def has_visible_locator(page, selectors: list[str]) -> bool:
            for selector in selectors:
                locator = page.locator(selector).first
                try:
                    if await locator.is_visible(timeout=750):
                        return True
                except Exception:
                    continue
            return False

        async def classify(page) -> str:
            return classify_x_auth_state(
                await body_text(page),
                page.url,
                login_input_visible=await has_visible_locator(page, X_LOGIN_INPUT_SELECTORS),
                authenticated_control_visible=await has_visible_locator(page, X_AUTH_CONTROL_SELECTORS),
            )

        async def submit_identifier(page, value: str) -> None:
            field = await first_visible(
                page,
                [
                    'input[autocomplete="username"]',
                    'input[name="text"]',
                    'input[type="text"]',
                ],
                timeout=9000,
            )
            if field is None:
                raise RuntimeError("X login identifier field was not found.")
            await fill_textbox(page, field, value)
            if not await click_first(
                [
                    ("next-role", lambda: page.get_by_role("button", name="Next")),
                    ("next-text", lambda: page.get_by_text("Next", exact=True)),
                ],
                timeout=4000,
            ):
                await field.press("Enter")
            await page.wait_for_timeout(3000)

        async def login_once(page) -> str:
            if not credentials:
                return "login_required"
            await page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2500)
            await submit_identifier(page, credentials.identifier)
            await screenshot(page, context, payload, "login-identifier-submitted", screenshots)

            text_after_identifier = (await body_text(page)).lower()
            if (
                "phone number or username" in text_after_identifier
                or "email address or phone number" in text_after_identifier
                or "confirm your" in text_after_identifier
            ):
                await submit_identifier(page, credentials.secondary_identifier or credentials.identifier)
                await screenshot(page, context, payload, "login-secondary-submitted", screenshots)

            password = await first_visible(
                page,
                ['input[name="password"]', 'input[type="password"]', 'input[autocomplete="current-password"]'],
                timeout=12000,
            )
            if password is None:
                return await classify(page)
            await fill_textbox(page, password, credentials.password)
            await screenshot(page, context, payload, "login-password-filled", screenshots)
            await password.press("Enter")
            await page.wait_for_timeout(9000)
            return await classify(page)

        async def ensure_authenticated(page) -> str:
            await page.goto(self.auth_start_url, wait_until="domcontentloaded", timeout=60000)
            state = "loading"
            for attempt in range(8):
                await page.wait_for_timeout(2000 if attempt else 3500)
                state = await classify(page)
                if state in {"authenticated", "login", "challenge"}:
                    break
                if attempt == 3:
                    await page.goto(self.auth_start_url, wait_until="domcontentloaded", timeout=60000)
            if state == "login":
                state = await login_once(page)
            return state

        async def upload_media(page) -> bool:
            if not files:
                return True
            file_input = page.locator('input[type="file"]').first
            try:
                await file_input.set_input_files(files, timeout=10000)
                await page.wait_for_timeout(3000)
                return True
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
                        message="X requires manual verification before posting.",
                        error_code=ErrorCode.CAPTCHA_OR_VERIFICATION,
                        raw={"auth_status": "challenge_required", "screenshots": screenshots},
                    )
                if auth_state != "authenticated":
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="X login is required before posting.",
                        error_code=ErrorCode.LOGIN_REQUIRED,
                        raw={"auth_status": "login_required", "screenshots": screenshots},
                    )

                await page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(3500)
                composer = await first_visible(
                    page,
                    [
                        '[data-testid="tweetTextarea_0"]',
                        'div[role="textbox"][contenteditable="true"]',
                    ],
                    timeout=12000,
                )
                if composer is None:
                    await screenshot(page, context, payload, "composer-not-found", screenshots)
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="X composer was not found.",
                        error_code=ErrorCode.COMPOSER_NOT_FOUND,
                        raw={"auth_status": "authenticated", "screenshots": screenshots},
                    )
                await fill_textbox(page, composer, text)
                await screenshot(page, context, payload, "text-filled", screenshots)

                if not await upload_media(page):
                    await screenshot(page, context, payload, "media-upload-failed", screenshots)
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="X media upload input did not accept the files.",
                        error_code=ErrorCode.MEDIA_UPLOAD_FAILED,
                        raw={"auth_status": "authenticated", "screenshots": screenshots},
                    )

                if not await click_first(
                    [
                        ("tweet-button", lambda: page.locator('[data-testid="tweetButton"]')),
                        ("tweet-inline-button", lambda: page.locator('[data-testid="tweetButtonInline"]')),
                        ("post-role", lambda: page.get_by_role("button", name="Post")),
                    ],
                    timeout=12000,
                ):
                    await screenshot(page, context, payload, "post-button-not-found", screenshots)
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="X Post button was not found or was disabled.",
                        error_code=ErrorCode.PUBLISH_BUTTON_DISABLED,
                        raw={"auth_status": "authenticated", "screenshots": screenshots},
                    )

                await page.wait_for_timeout(7000)
                await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(5000)
                await screenshot(page, context, payload, "post-submitted", screenshots)
                page_text = await body_text(page)
                if text[:40] in page_text:
                    return PlatformResult(
                        platform=payload.platform,
                        status="success",
                        message="X post published.",
                        raw={"auth_status": "authenticated", "screenshots": screenshots},
                    )
                if any(marker in page_text.lower() for marker in ["try again", "something went wrong", "not sent"]):
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="X reported an error after submitting the post.",
                        error_code=ErrorCode.UNKNOWN_UI_STATE,
                        raw={"auth_status": "authenticated", "screenshots": screenshots},
                    )
                return PlatformResult(
                    platform=payload.platform,
                    status="success",
                    message="X post submitted; direct timeline confirmation was not visible yet.",
                    raw={"auth_status": "authenticated", "screenshots": screenshots},
                )
            finally:
                await browser.close()

    def task_prompt(self, payload: PlatformTaskPayload, context: WorkerContext, asset_lookup: dict[str, str]) -> str:
        media = media_paths(payload, context, asset_lookup)
        media_line = f"Upload these media files: {media}" if media else "No media upload is required."
        return f"""
Go to https://x.com/compose/post using the existing logged-in browser profile.
Create and publish this post for account {payload.account}.

Post text:
{content_text(payload)}

{media_line}

For a single post, use the composer textbox such as `tweetTextarea_0`, enter the post text exactly once, then click
the exact enabled single-post publish button such as `tweetButton` or `tweetButtonInline`.
Do not click "Add post" or "Post all" unless the content mode is a thread with multiple posts.
After publishing, return any visible post URL or success confirmation.
If cookie banners, onboarding prompts, or non-critical popups block the composer, close them.
If the UI is uncertain or asks for verification, stop and report the blocker instead of publishing.
"""
