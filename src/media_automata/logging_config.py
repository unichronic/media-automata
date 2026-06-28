from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
QUIET_LOGGER_PREFIXES = (
    "media_automata.agents.llm",
    "media_automata.platforms.browser_use_llm",
    "httpx",
    "httpcore",
)


class ISTFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created, IST)
        return dt.strftime("%d %b %Y %I:%M:%S %p IST")


def configure_logging(*, level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(ISTFormatter(DEFAULT_LOG_FORMAT))
        root.addHandler(handler)
    root.setLevel(level)
    for name in QUIET_LOGGER_PREFIXES:
        logging.getLogger(name).setLevel(logging.WARNING)
