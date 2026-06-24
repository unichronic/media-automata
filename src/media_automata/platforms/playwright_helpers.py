from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from media_automata.platforms.base import WorkerContext
from media_automata.schemas import PlatformTaskPayload


def chromium_launch_kwargs() -> dict[str, Any]:
    configured = (
        os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
        or os.environ.get("PUPPETEER_EXECUTABLE_PATH")
    )
    candidates = [configured]
    browser_roots = [
        Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")),
        Path.home() / ".cache" / "ms-playwright",
    ]
    for root in browser_roots:
        if not str(root) or not root.exists():
            continue
        candidates.extend(
            str(path)
            for pattern in ("chromium-*/chrome-linux*/chrome", "chromium-*/chrome-linux/chrome")
            for path in sorted(root.glob(pattern), reverse=True)
        )
    candidates.extend(
        [
            shutil.which("google-chrome"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
        ]
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return {"executable_path": str(candidate)}
    return {}


async def body_text(page: Any) -> str:
    try:
        return await page.locator("body").inner_text(timeout=5000)
    except Exception:
        return ""


async def screenshot(
    page: Any,
    context: WorkerContext,
    payload: PlatformTaskPayload,
    name: str,
    screenshots: list[str],
) -> None:
    path = context.artifact_root / f"{payload.platform.value}-{payload.job_id}-{name}.png"
    await page.screenshot(path=str(path), full_page=True)
    screenshots.append(str(path))


async def first_visible(page: Any, selectors: list[str], timeout: int = 4000) -> Any | None:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            await locator.wait_for(state="visible", timeout=timeout)
            return locator
        except Exception:
            continue
    return None


async def click_first(
    candidates: list[tuple[str, Callable[[], Any]]],
    *,
    timeout: int = 4000,
) -> bool:
    for _, candidate in candidates:
        locator = candidate().first
        try:
            await locator.wait_for(state="visible", timeout=timeout)
            if hasattr(locator, "is_enabled") and not await locator.is_enabled(timeout=timeout):
                continue
            await locator.click(timeout=timeout)
            return True
        except Exception:
            continue
    return False


async def fill_textbox(page: Any, locator: Any, text: str) -> None:
    await locator.click(timeout=5000)
    try:
        await locator.fill(text, timeout=4000)
    except Exception:
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await page.keyboard.insert_text(text)
