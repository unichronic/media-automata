from __future__ import annotations

from pathlib import Path

CHROMIUM_PROFILE_LOCKS = ("SingletonLock", "SingletonSocket", "SingletonCookie")


def prepare_persistent_profile(profile_path: Path) -> None:
    profile_path.mkdir(parents=True, exist_ok=True)
    for lock_name in CHROMIUM_PROFILE_LOCKS:
        lock_path = profile_path / lock_name
        try:
            if lock_path.is_symlink() or lock_path.is_file() or lock_path.exists():
                lock_path.unlink()
        except OSError:
            continue


def persistent_browser_args(*, window_size: str = "1400,1000") -> list[str]:
    return [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-infobars",
        "--disable-blink-features=AutomationControlled",
        "--disable-features=ClipboardContentSetting",
        "--no-first-run",
        "--no-default-browser-check",
        "--password-store=basic",
        "--use-mock-keychain",
        f"--window-size={window_size}",
    ]
