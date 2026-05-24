from __future__ import annotations

from media_automata.config import Settings
from media_automata.platforms.base import PlatformWorker
from media_automata.platforms.instagram import InstagramWorker
from media_automata.platforms.linkedin import LinkedInWorker
from media_automata.platforms.x import XWorker
from media_automata.schemas import Platform


def build_platform_worker(platform: Platform | str, settings: Settings) -> PlatformWorker:
    platform_value = Platform(platform)
    if platform_value == Platform.LINKEDIN:
        return LinkedInWorker()
    if platform_value == Platform.X:
        return XWorker()
    if platform_value == Platform.INSTAGRAM:
        return InstagramWorker()
    raise ValueError(f"Unsupported platform: {platform}")
