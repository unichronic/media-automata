from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from media_automata.instagram_story_actions import (
    INSTAGRAM_STORY_EDITOR_ACTIONS_KEY,
    INSTAGRAM_STORY_REQUIRES_NATIVE_KEY,
)
from media_automata.platforms.base import WorkerContext
from media_automata.platforms.browser_use_worker import BrowserUsePlatformWorker, content_text, media_paths
from media_automata.platforms.instagram_native import InstagramNativeWorker
from media_automata.platforms.playwright_helpers import (
    body_text,
    click_first,
    fill_textbox,
    first_visible,
    screenshot,
)
from media_automata.platforms.profile import persistent_browser_args, prepare_persistent_profile
from media_automata.schemas import ErrorCode, PlatformResult, PlatformTaskPayload

LOGIN_SELECTORS = [
    'input[name="email"]',
    'input[autocomplete*="username"]',
    'input[type="text"]',
    'input[aria-label*="username" i]',
    'input[aria-label*="email" i]',
]
PASSWORD_SELECTORS = [
    'input[name="pass"]',
    'input[type="password"]',
    'input[autocomplete="current-password"]',
]
AUTH_MARKERS = ("home", "search", "explore", "reels", "messages", "notifications", "create", "profile")
AUTH_CONTROL_SELECTORS = [
    'svg[aria-label="Home"]',
    'a[href="/"]',
    'a[href="/explore/"]',
    'a[href="/reels/"]',
    '[aria-label*="Home" i]',
    '[aria-label*="Create" i]',
    '[aria-label*="New post" i]',
    '[aria-label*="Profile" i]',
]
LOGIN_INPUT_SELECTORS = [
    'input[name="username"]:visible',
    'input[autocomplete*="username" i]:visible',
    'input[aria-label*="username" i]:visible',
    'input[aria-label*="email" i]:visible',
]
CHALLENGE_MARKERS = (
    "check your email",
    "enter the code",
    "security code",
    "verification",
    "confirm your",
    "challenge",
    "captcha",
    "suspicious",
)
LOGIN_MARKERS = ("log into instagram", "mobile number, username or email", "forgot password")
STORY_ERROR_MARKERS = ("couldn't share", "could not share", "try again", "error", "upload failed")
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}


def classify_instagram_auth_state(
    text: str,
    url: str,
    *,
    password_input_visible: bool = False,
    login_input_visible: bool = False,
    authenticated_control_visible: bool = False,
) -> str:
    page_text = text.lower()
    current_url = url.lower()
    if "codeentry" in current_url or any(marker in page_text for marker in CHALLENGE_MARKERS):
        return "challenge"

    if authenticated_control_visible or "your story" in page_text:
        return "authenticated"
    if "accounts/login" not in current_url and any(marker in page_text for marker in AUTH_MARKERS):
        return "authenticated"

    if (
        "accounts/login" in current_url
        or password_input_visible
        or login_input_visible
        or any(marker in page_text for marker in LOGIN_MARKERS)
    ):
        return "login"
    return "unknown"


async def has_visible_locator(page: Any, selectors: list[str]) -> bool:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.is_visible(timeout=750):
                return True
        except Exception:
            continue
    return False


def classify_story_publish_state(text: str) -> Literal["error", "success", "uploading", "unknown"]:
    page_text = text.lower()
    if any(marker in page_text for marker in STORY_ERROR_MARKERS):
        return "error"
    if "uploading" in page_text:
        return "uploading"
    if "add to your story" not in page_text and ("your story" in page_text or "home" in page_text):
        return "success"
    return "unknown"


def instagram_profile_slug(identifier: str | None) -> str | None:
    clean = (identifier or "").strip().lstrip("@")
    if not clean or "@" in clean or "/" in clean or "\\" in clean:
        return None
    return clean


class InstagramWorker(BrowserUsePlatformWorker):
    allowed_domains = ["instagram.com", "*.instagram.com"]
    mistral_purpose = "browser:instagram"
    auth_start_url = "https://www.instagram.com/"
    auth_success_description = (
        "the Instagram home feed, create button, profile avatar, or authenticated navigation is visible"
    )
    auth_login_description = (
        "Instagram login form, signup prompt, password screen, or verification challenge is visible"
    )

    async def publish_post(
        self,
        payload: PlatformTaskPayload,
        context: WorkerContext,
        asset_lookup: dict[str, str],
    ) -> PlatformResult:
        if payload.content.mode == "story":
            actions = payload.content.extra.get(INSTAGRAM_STORY_EDITOR_ACTIONS_KEY) or []
            if payload.content.extra.get("instagram_story_source") == "feed_post":
                return await InstagramNativeWorker().share_latest_feed_post_to_story(payload, context)
            if actions or payload.content.extra.get(INSTAGRAM_STORY_REQUIRES_NATIVE_KEY):
                return await InstagramNativeWorker().publish_direct_media_story(payload, context, asset_lookup)
            return await self._publish_story_with_playwright(payload, context, asset_lookup)
        return await self._publish_with_playwright(payload, context, asset_lookup)

    async def _publish_with_playwright(
        self,
        payload: PlatformTaskPayload,
        context: WorkerContext,
        asset_lookup: dict[str, str],
    ) -> PlatformResult:
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            from playwright.async_api import async_playwright
        except Exception as exc:  # pragma: no cover - exercised only when optional dependency is absent
            return PlatformResult(
                platform=payload.platform,
                status="failed",
                message=f"Playwright is not installed: {exc}",
                error_code=ErrorCode.INTERNAL_ERROR,
            )

        media = media_paths(payload, context, asset_lookup)
        is_reel = payload.content.mode == "reel"
        if not media:
            return PlatformResult(
                platform=payload.platform,
                status="failed",
                message=(
                    "Instagram Reel publishing requires a video media asset."
                    if is_reel
                    else "Instagram feed posting requires at least one media asset."
                ),
                error_code=ErrorCode.CONTENT_REJECTED,
            )
        if is_reel and not any(Path(path).suffix.lower() in VIDEO_EXTENSIONS for path in media):
            return PlatformResult(
                platform=payload.platform,
                status="failed",
                message="Instagram Reel publishing requires a video media asset.",
                error_code=ErrorCode.CONTENT_REJECTED,
            )

        screenshots: list[str] = []
        caption = content_text(payload)
        credentials = context.settings.platform_login_credentials(str(payload.platform))

        async def body_text(page) -> str:
            try:
                return await page.locator("body").inner_text(timeout=5000)
            except Exception:
                return ""

        async def screenshot(page, name: str) -> None:
            path = context.artifact_root / f"instagram-{payload.job_id}-{name}.png"
            await page.screenshot(path=str(path), full_page=True)
            screenshots.append(str(path))

        async def classify(page) -> str:
            return classify_instagram_auth_state(
                await body_text(page),
                page.url,
                password_input_visible=await has_visible_locator(page, ['input[type="password"]']),
                login_input_visible=await has_visible_locator(page, LOGIN_INPUT_SELECTORS),
                authenticated_control_visible=await has_visible_locator(page, AUTH_CONTROL_SELECTORS),
            )

        async def first_visible(page, selectors: list[str]):
            for selector in selectors:
                locator = page.locator(selector).first
                try:
                    await locator.wait_for(state="visible", timeout=4000)
                    return locator
                except PlaywrightTimeoutError:
                    continue
            return None

        async def click_any(page, candidates: list[tuple[str, Callable[[], Any]]], timeout: int = 4000) -> bool:
            for _, candidate in candidates:
                locator = candidate().first
                try:
                    await locator.wait_for(state="visible", timeout=timeout)
                    await locator.click(timeout=timeout)
                    return True
                except Exception:
                    continue
            return False

        async def dismiss_popups(page) -> None:
            for _ in range(4):
                text = (await body_text(page)).lower()
                if "save your login info" in text:
                    clicked = await click_any(
                        page,
                        [
                            ("save-info", lambda: page.get_by_text("Save info", exact=True)),
                            ("not-now", lambda: page.get_by_text("Not now", exact=True)),
                        ],
                    )
                    if clicked:
                        await page.wait_for_timeout(2000)
                        continue
                if "turn on notifications" in text or "notifications" in text:
                    clicked = await click_any(
                        page,
                        [
                            ("not-now-title", lambda: page.get_by_text("Not Now", exact=True)),
                            ("not-now", lambda: page.get_by_text("Not now", exact=True)),
                        ],
                    )
                    if clicked:
                        await page.wait_for_timeout(1500)
                        continue
                break

        async def login_once(page) -> str:
            if not credentials:
                return "login_required"
            user = await first_visible(page, LOGIN_SELECTORS)
            password = await first_visible(page, PASSWORD_SELECTORS)
            if user is None or password is None:
                return "login_required"
            await user.click()
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await page.keyboard.type(credentials.identifier, delay=35)
            await password.click()
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await page.keyboard.type(credentials.password, delay=35)
            await screenshot(page, "login-filled")
            await password.press("Enter")
            await page.wait_for_timeout(9000)
            try:
                await page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            return await classify(page)

        async def ensure_authenticated(page) -> str:
            state = await classify(page)
            if state == "login":
                state = await login_once(page)
            if state == "authenticated":
                await dismiss_popups(page)
                state = await classify(page)
            return state

        async def upload_surface_ready(page) -> bool:
            if await page.locator('input[type="file"]').count():
                return True
            return await has_visible_locator(
                page,
                [
                    'text="Select from computer"',
                    'text="Select from device"',
                    'button:has-text("Select from computer")',
                    'button:has-text("Select from device")',
                ],
            )

        async def open_create_dialog(page) -> bool:
            if await upload_surface_ready(page):
                return True

            create_clicked = await click_any(
                page,
                [
                    ("new-post-anchor", lambda: page.locator('[aria-label="New post"]').locator('xpath=ancestor::a[1]')),
                    ("create-href", lambda: page.locator('a[href="/create/select/"]')),
                    ("create-any-href", lambda: page.locator('a[href*="/create"]')),
                    ("create-text", lambda: page.get_by_text("Create", exact=True).locator('xpath=ancestor::a[1]')),
                    ("create-button", lambda: page.get_by_role("button", name="Create")),
                    ("new-post-label", lambda: page.locator('[aria-label="New post"]')),
                ],
                timeout=6000,
            )
            if not create_clicked:
                return False

            for _ in range(8):
                await page.wait_for_timeout(1000)
                if await upload_surface_ready(page):
                    return True
                await click_any(
                    page,
                    [
                        ("post-submenu-anchor", lambda: page.locator('span:has-text("Post"):visible').locator('xpath=ancestor::a[1]')),
                        (
                            "post-submenu-clickable",
                            lambda: page.locator('span:has-text("Post"):visible').locator(
                                'xpath=ancestor::*[@role="button" or self::button or self::a][1]'
                            ),
                        ),
                        ("select-from-computer", lambda: page.get_by_text("Select from computer", exact=True)),
                    ],
                    timeout=1500,
                )
            return await upload_surface_ready(page)

        async def select_upload_file(page) -> bool:
            file_input = page.locator('input[type="file"]').first
            try:
                await file_input.wait_for(state="attached", timeout=15000)
                await file_input.set_input_files(media[0], timeout=10000)
                return True
            except Exception:
                try:
                    async with page.expect_file_chooser(timeout=8000) as file_chooser:
                        clicked = await click_any(
                            page,
                            [
                                ("select-from-computer", lambda: page.get_by_text("Select from computer", exact=True)),
                                ("select-from-device", lambda: page.get_by_text("Select from device", exact=True)),
                            ],
                            timeout=5000,
                        )
                        if not clicked:
                            return False
                    chooser = await file_chooser.value
                    await chooser.set_files(media[0])
                    return True
                except Exception:
                    return False

        async def next_steps(page) -> None:
            for _ in range(2):
                clicked = await click_any(
                    page,
                    [
                        ("next-text", lambda: page.get_by_text("Next", exact=True)),
                        ("next-role", lambda: page.get_by_role("button", name="Next")),
                    ],
                    timeout=9000,
                )
                if not clicked:
                    return
                await page.wait_for_timeout(3000)

        async def fill_caption(page) -> bool:
            for locator in (
                page.locator("textarea").first,
                page.get_by_role("textbox").first,
                page.locator('[contenteditable="true"]').first,
            ):
                try:
                    await locator.wait_for(state="visible", timeout=5000)
                    await locator.click(timeout=3000)
                    try:
                        await locator.fill(caption, timeout=3000)
                    except Exception:
                        await page.keyboard.type(caption, delay=15)
                    return True
                except Exception:
                    continue
            return False

        async def latest_profile_post_url(page) -> str | None:
            slug = instagram_profile_slug(context.settings.instagram_username)
            if not slug:
                return None
            try:
                await page.goto(f"https://www.instagram.com/{slug}/", wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(6000)
                urls = await page.locator('a[href*="/p/"], a[href*="/reel/"]').evaluate_all(
                    "(links) => links.slice(0, 1).map((link) => link.href)"
                )
            except Exception:
                return None
            if not urls:
                return None
            return str(urls[0])

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
                await page.goto(self.auth_start_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(3500)
                auth_state = await ensure_authenticated(page)
                await screenshot(page, "auth-state")
                if auth_state == "challenge":
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="Instagram requires manual verification before posting.",
                        error_code=ErrorCode.CAPTCHA_OR_VERIFICATION,
                        raw={"auth_status": "challenge_required", "screenshots": screenshots},
                    )
                if auth_state != "authenticated":
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="Instagram login is required before posting.",
                        error_code=ErrorCode.LOGIN_REQUIRED,
                        raw={"auth_status": "login_required", "screenshots": screenshots},
                    )

                if not await open_create_dialog(page):
                    await screenshot(page, "create-not-found")
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="Instagram create/new-post control was not found.",
                        error_code=ErrorCode.COMPOSER_NOT_FOUND,
                        raw={"auth_status": "authenticated", "screenshots": screenshots},
                    )
                await page.wait_for_timeout(2500)
                await screenshot(page, "create-opened")

                if not await select_upload_file(page):
                    await screenshot(page, "upload-failed")
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="Instagram media upload input was not found or did not accept the file.",
                        error_code=ErrorCode.MEDIA_UPLOAD_FAILED,
                        raw={"auth_status": "authenticated", "screenshots": screenshots},
                    )
                await page.wait_for_timeout(9000 if is_reel else 4000)
                await screenshot(page, "file-selected")

                await next_steps(page)
                await screenshot(page, "caption-step")
                if not await fill_caption(page):
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="Instagram caption field was not found.",
                        error_code=ErrorCode.COMPOSER_NOT_FOUND,
                        raw={"auth_status": "authenticated", "screenshots": screenshots},
                    )
                await screenshot(page, "caption-filled")

                if not await click_any(
                    page,
                    [
                        ("share-text", lambda: page.get_by_text("Share", exact=True)),
                        ("share-role", lambda: page.get_by_role("button", name="Share")),
                    ],
                    timeout=9000,
                ):
                    await screenshot(page, "share-not-found")
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="Instagram Share button was not found.",
                        error_code=ErrorCode.PUBLISH_BUTTON_DISABLED,
                        raw={"auth_status": "authenticated", "screenshots": screenshots},
                    )

                for _ in range(180 if is_reel else 90):
                    await page.wait_for_timeout(1000)
                    text = (await body_text(page)).lower()
                    if (
                        "your post has been shared" in text
                        or "post shared" in text
                        or "your reel has been shared" in text
                        or "reel shared" in text
                    ):
                        await screenshot(page, "shared")
                        result_url = await latest_profile_post_url(page)
                        return PlatformResult(
                            platform=payload.platform,
                            status="success",
                            result_url=result_url,
                            message="Instagram Reel shared." if is_reel else "Instagram post shared.",
                            raw={"auth_status": "authenticated", "screenshots": screenshots},
                        )
                    if any(marker in text for marker in ["couldn't share", "not posted", "try again", "error"]):
                        await screenshot(page, "share-error")
                        return PlatformResult(
                            platform=payload.platform,
                            status="failed",
                            message="Instagram reported an error while sharing the post.",
                            error_code=ErrorCode.UNKNOWN_UI_STATE,
                            raw={"auth_status": "authenticated", "screenshots": screenshots},
                        )
                await screenshot(page, "share-timeout")
                return PlatformResult(
                    platform=payload.platform,
                    status="failed",
                    message=(
                        "Instagram Reel share confirmation did not appear before timeout."
                        if is_reel
                        else "Instagram share confirmation did not appear before timeout."
                    ),
                    error_code=ErrorCode.NETWORK_TIMEOUT,
                    raw={"auth_status": "authenticated", "screenshots": screenshots},
                )
            finally:
                await browser.close()

    async def _publish_story_with_playwright(
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

        story_source = str(payload.content.extra.get("instagram_story_source", "media"))
        media = media_paths(payload, context, asset_lookup)
        if story_source != "feed_post" and not media:
            return PlatformResult(
                platform=payload.platform,
                status="failed",
                message="Instagram Story publishing requires at least one media asset.",
                error_code=ErrorCode.CONTENT_REJECTED,
            )

        screenshots: list[str] = []
        credentials = context.settings.platform_login_credentials(str(payload.platform))

        async def classify(page) -> str:
            return classify_instagram_auth_state(
                await body_text(page),
                page.url,
                password_input_visible=await has_visible_locator(page, ['input[type="password"]']),
                login_input_visible=await has_visible_locator(page, LOGIN_INPUT_SELECTORS),
                authenticated_control_visible=await has_visible_locator(page, AUTH_CONTROL_SELECTORS),
            )

        async def login_once(page) -> str:
            if not credentials:
                return "login_required"
            user = await first_visible(page, LOGIN_SELECTORS)
            password = await first_visible(page, PASSWORD_SELECTORS)
            if user is None or password is None:
                return "login_required"
            await fill_textbox(page, user, credentials.identifier)
            await fill_textbox(page, password, credentials.password)
            await screenshot(page, context, payload, "story-login-filled", screenshots)
            await password.press("Enter")
            await page.wait_for_timeout(9000)
            try:
                await page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            return await classify(page)

        async def ensure_authenticated(page) -> str:
            state = await classify(page)
            if state == "login":
                state = await login_once(page)
            if state == "authenticated":
                await dismiss_story_popups(page)
                state = await classify(page)
            return state

        async def dismiss_story_popups(page) -> None:
            for _ in range(4):
                text = (await body_text(page)).lower()
                clicked = False
                if "save your login info" in text:
                    clicked = await click_first(
                        [
                            ("not-now", lambda: page.get_by_text("Not now", exact=True)),
                            ("save-info", lambda: page.get_by_text("Save info", exact=True)),
                        ],
                        timeout=3000,
                    )
                elif "turn on notifications" in text or "notifications" in text:
                    clicked = await click_first(
                        [
                            ("not-now-title", lambda: page.get_by_text("Not Now", exact=True)),
                            ("not-now", lambda: page.get_by_text("Not now", exact=True)),
                        ],
                        timeout=3000,
                    )
                if not clicked:
                    return
                await page.wait_for_timeout(1500)

        async def story_editor_visible(page) -> bool:
            text = (await body_text(page)).lower()
            url = page.url.lower()
            markers = ("add to your story", "your story", "story")
            return "stories" in url or "story" in url or any(marker in text for marker in markers)

        async def open_story_editor(page) -> bool:
            if await click_first(
                [
                    ("your-story", lambda: page.get_by_text("Your story", exact=True)),
                    ("story-camera", lambda: page.locator('[aria-label*="Story" i]')),
                    ("camera", lambda: page.locator('[aria-label*="Camera" i]')),
                ],
                timeout=4000,
            ):
                await page.wait_for_timeout(2000)
                try:
                    file_input = page.locator('input[type="file"]').first
                    await file_input.set_input_files(media[0], timeout=8000)
                    await page.wait_for_timeout(5000)
                    if await story_editor_visible(page):
                        return True
                except Exception:
                    pass

            await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)
            count = await page.locator('input[type="file"]').count()
            for index in reversed(range(count)):
                try:
                    file_input = page.locator('input[type="file"]').nth(index)
                    await file_input.set_input_files(media[0], timeout=8000)
                    await page.wait_for_timeout(5000)
                    await screenshot(page, context, payload, f"story-input-{index}", screenshots)
                    if await story_editor_visible(page):
                        return True
                    await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=60000)
                    await page.wait_for_timeout(3000)
                except Exception:
                    continue
            return False

        async def open_profile(page) -> bool:
            slug = instagram_profile_slug(context.settings.instagram_username)
            if slug:
                await page.goto(f"https://www.instagram.com/{slug}/", wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(3500)
                return True
            await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2500)
            clicked = await click_first(
                [
                    ("profile-label", lambda: page.locator('[aria-label*="Profile" i]')),
                    ("profile-link", lambda: page.locator('a[href^="/"][href$="/"]')),
                ],
                timeout=5000,
            )
            if clicked:
                await page.wait_for_timeout(3500)
            return clicked

        async def open_feed_post_story_editor(page) -> bool:
            if not await open_profile(page):
                return False
            await screenshot(page, context, payload, "story-profile-opened", screenshots)

            if not await click_first(
                [
                    ("latest-post", lambda: page.locator('a[href*="/p/"], a[href*="/reel/"]')),
                    ("latest-grid-cell", lambda: page.locator('main a[role="link"]')),
                ],
                timeout=9000,
            ):
                return False
            await page.wait_for_timeout(3500)
            await screenshot(page, context, payload, "story-feed-post-opened", screenshots)

            if not await click_first(
                [
                    ("share-label", lambda: page.locator('[aria-label="Share"], [aria-label="Send"]')),
                    ("share-role", lambda: page.get_by_role("button", name="Share")),
                    ("send-role", lambda: page.get_by_role("button", name="Send")),
                ],
                timeout=7000,
            ):
                return False
            await page.wait_for_timeout(2500)
            await screenshot(page, context, payload, "story-feed-post-share-opened", screenshots)

            if not await click_first(
                [
                    ("add-post-to-story", lambda: page.get_by_text("Add post to your story", exact=False)),
                    ("add-to-story", lambda: page.get_by_text("Add to story", exact=False)),
                    ("add-to-your-story", lambda: page.get_by_text("Add to your story", exact=False)),
                ],
                timeout=9000,
            ):
                return False
            await page.wait_for_timeout(5000)
            return await story_editor_visible(page)

        async def publish_story(page) -> bool:
            return await click_first(
                [
                    ("add-to-your-story", lambda: page.get_by_text("Add to your story", exact=True)),
                    ("your-story-button", lambda: page.get_by_role("button", name="Your story")),
                    ("share", lambda: page.get_by_text("Share", exact=True)),
                ],
                timeout=8000,
            )

        async with async_playwright() as playwright:
            prepare_persistent_profile(context.profile_path)
            browser = await playwright.chromium.launch_persistent_context(
                str(context.profile_path),
                headless=context.settings.browser_headless,
                viewport={"width": 390, "height": 844},
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
                ),
                is_mobile=True,
                has_touch=True,
                args=persistent_browser_args(window_size="390,844"),
            )
            page = browser.pages[0] if browser.pages else await browser.new_page()
            try:
                await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(3500)
                auth_state = await ensure_authenticated(page)
                await screenshot(page, context, payload, "story-auth-state", screenshots)
                if auth_state == "challenge":
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="Instagram requires manual verification before Story publishing.",
                        error_code=ErrorCode.CAPTCHA_OR_VERIFICATION,
                        raw={"auth_status": "challenge_required", "screenshots": screenshots},
                    )
                if auth_state != "authenticated":
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="Instagram login is required before Story publishing.",
                        error_code=ErrorCode.LOGIN_REQUIRED,
                        raw={"auth_status": "login_required", "screenshots": screenshots},
                    )

                open_story = open_feed_post_story_editor if story_source == "feed_post" else open_story_editor
                if not await open_story(page):
                    await screenshot(page, context, payload, "story-editor-not-found", screenshots)
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="Instagram Story creation control was not found.",
                        error_code=ErrorCode.COMPOSER_NOT_FOUND,
                        raw={"auth_status": "authenticated", "screenshots": screenshots},
                    )
                await screenshot(page, context, payload, "story-editor-opened", screenshots)

                if not await publish_story(page):
                    await screenshot(page, context, payload, "story-share-not-found", screenshots)
                    return PlatformResult(
                        platform=payload.platform,
                        status="failed",
                        message="Instagram Story share button was not found.",
                        error_code=ErrorCode.PUBLISH_BUTTON_DISABLED,
                        raw={"auth_status": "authenticated", "screenshots": screenshots},
                    )

                upload_started = False
                for _ in range(180):
                    await page.wait_for_timeout(1000)
                    state = classify_story_publish_state(await body_text(page))
                    if state == "error":
                        await screenshot(page, context, payload, "story-share-error", screenshots)
                        return PlatformResult(
                            platform=payload.platform,
                            status="failed",
                            message="Instagram reported an error while sharing the Story.",
                            error_code=ErrorCode.UNKNOWN_UI_STATE,
                            raw={"auth_status": "authenticated", "screenshots": screenshots},
                        )
                    if state == "success":
                        await screenshot(page, context, payload, "story-shared", screenshots)
                        return PlatformResult(
                            platform=payload.platform,
                            status="success",
                            message="Instagram Story shared.",
                            raw={"auth_status": "authenticated", "screenshots": screenshots},
                        )
                    if state == "uploading":
                        upload_started = True

                await screenshot(page, context, payload, "story-share-timeout", screenshots)
                if upload_started:
                    return PlatformResult(
                        platform=payload.platform,
                        status="success",
                        message="Instagram Story upload submitted; final confirmation was not visible before timeout.",
                        raw={"auth_status": "authenticated", "screenshots": screenshots},
                    )
                return PlatformResult(
                    platform=payload.platform,
                    status="failed",
                    message="Instagram Story confirmation did not appear before timeout.",
                    error_code=ErrorCode.NETWORK_TIMEOUT,
                    raw={"auth_status": "authenticated", "screenshots": screenshots},
                )
            finally:
                await browser.close()

    def task_prompt(self, payload: PlatformTaskPayload, context: WorkerContext, asset_lookup: dict[str, str]) -> str:
        media = media_paths(payload, context, asset_lookup)
        media_line = (
            f"Upload these media files: {media}"
            if media
            else "No media was provided; create a text/caption draft if possible."
        )
        if payload.content.mode == "story":
            story_source = payload.content.extra.get("instagram_story_source", "media")
            story_action = (
                "Share the latest Instagram feed post from this account into a Story."
                if story_source == "feed_post"
                else "Upload the provided media directly as a Story."
            )
            return f"""
Go to Instagram using the existing logged-in browser profile.
Create and publish a Story for account {payload.account}.

Story text/caption context:
{content_text(payload)}

Story source:
{story_action}

{media_line}

Use Instagram's story creation flow when available, including the mobile-web "Your story" upload path if the web UI
exposes it.
Complete the upload and share/post the Story.
If the UI only exposes feed-post creation, or if verification appears, stop and report the blocker instead of
publishing.
"""
        return f"""
Go to Instagram using the existing logged-in browser profile.
Create and publish a feed post for account {payload.account}.

Caption:
{content_text(payload)}

{media_line}

Use the standard create/new post flow, complete the upload, share the post,
and return confirmation text when the post is shared.
If cookie banners, onboarding prompts, or non-critical popups block the composer, close them.
If the UI is uncertain or asks for verification, stop and report the blocker instead of publishing.
"""
