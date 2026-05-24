from __future__ import annotations

import asyncio

from media_automata.config import get_settings
from media_automata.worker import BrowserTaskRunner


async def main() -> None:
    await BrowserTaskRunner(get_settings()).run_loop()


if __name__ == "__main__":
    asyncio.run(main())

