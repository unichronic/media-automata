from __future__ import annotations

import re
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Asia/Kolkata"

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

RELATIVE_DAY_RE = re.compile(
    r"\b(?P<day>today|tomorrow)\b(?:\s+(?:at|for))?\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)?\b",
    re.IGNORECASE,
)
MONTH_FIRST_RE = re.compile(
    r"\b(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+"
    r"(?P<day>\d{1,2})(?:,?\s+(?P<year>\d{4}))?"
    r"(?:\s+(?:at|for))?\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)?\b",
    re.IGNORECASE,
)
DAY_FIRST_RE = re.compile(
    r"\b(?P<day>\d{1,2})\s+"
    r"(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"(?:,?\s+(?P<year>\d{4}))?"
    r"(?:\s+(?:at|for))?\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)?\b",
    re.IGNORECASE,
)
ISO_LIKE_RE = re.compile(
    r"\b(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})"
    r"(?:[T\s]+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?)?"
    r"(?:\s*(?P<ampm>am|pm))?\b",
    re.IGNORECASE,
)
_MONTH = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
AT_MONTH_DAY_TIME_RE = re.compile(
    rf"\b(?:at|for)\s+(?P<month>{_MONTH})\s+"
    r"(?P<day>\d{1,2})(?:,?\s+(?P<year>\d{4}))?"
    r"\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)?\b",
    re.IGNORECASE,
)
AT_TIME_MONTH_DAY_RE = re.compile(
    rf"\b(?:at|for)\s+(?P<hour>\d{{1,2}}):(?P<minute>\d{{2}})\s+"
    rf"(?P<month>{_MONTH})\s+"
    r"(?P<day>\d{1,2})(?:,?\s+(?P<year>\d{4}))?\b",
    re.IGNORECASE,
)


def parse_scheduled_for(
    *values: str | None,
    now: datetime | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> datetime | None:
    """Parse a user or LLM schedule string and return a UTC datetime.

    The parser intentionally covers the command forms this product expects from WhatsApp:
    ISO strings, "May 26 12 PM", "26 May 12 PM", and "tomorrow 9:30am".
    """

    tz = ZoneInfo(timezone_name)
    reference = now or datetime.now(tz)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=tz)
    reference = reference.astimezone(tz)

    for raw in values:
        value = (raw or "").strip()
        if not value:
            continue
        for candidate in _schedule_candidates(value):
            parsed = _parse_iso_datetime(candidate, tz) or _parse_known_phrases(candidate, reference, tz)
            if parsed:
                return parsed.astimezone(UTC)
    return None


def is_future_schedule(scheduled_for: datetime, *, now: datetime | None = None) -> bool:
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    if scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=UTC)
    return scheduled_for.astimezone(UTC) > reference.astimezone(UTC)


def _parse_iso_datetime(value: str, tz: ZoneInfo) -> datetime | None:
    candidate = _extract_iso_candidate(value)
    if not candidate:
        return None
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed


def _extract_iso_candidate(value: str) -> str | None:
    iso_pattern = r"\d{4}-\d{1,2}-\d{1,2}(?:[T\s]\d{1,2}(?::\d{2})?(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)?"
    for token in re.findall(iso_pattern, value):
        return token.strip()
    return None


def _parse_known_phrases(value: str, reference: datetime, tz: ZoneInfo) -> datetime | None:
    for regex in (
        AT_TIME_MONTH_DAY_RE,
        AT_MONTH_DAY_TIME_RE,
        RELATIVE_DAY_RE,
        MONTH_FIRST_RE,
        DAY_FIRST_RE,
        ISO_LIKE_RE,
    ):
        match = regex.search(value)
        if not match:
            continue
        parsed = _datetime_from_match(match.groupdict(), reference, tz)
        if parsed is not None:
            return parsed
    return None


def _datetime_from_match(parts: dict[str, str | None], reference: datetime, tz: ZoneInfo) -> datetime | None:
    hour, minute = _parse_time(parts.get("hour"), parts.get("minute"), parts.get("ampm"))
    if not _valid_clock(hour, minute):
        return None
    if parts.get("day", "").lower() in {"today", "tomorrow"}:
        base = reference.date()
        if parts["day"].lower() == "tomorrow":
            base += timedelta(days=1)
        return _safe_datetime(base.year, base.month, base.day, hour, minute, tz)

    month_value = parts.get("month")
    if not month_value or month_value.lower() not in MONTHS:
        return _date_from_numbers(parts, reference, tz, hour, minute)
    month = MONTHS[month_value.lower()]
    day = int(parts["day"])
    year = int(parts["year"]) if parts.get("year") else reference.year
    parsed = _safe_datetime(year, month, day, hour, minute, tz)
    if parsed is None:
        return None
    if not parts.get("year") and (month, day) < (reference.month, reference.day):
        parsed = parsed.replace(year=year + 1)
    return parsed


def _schedule_candidates(value: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(candidate: str | None) -> None:
        clean = (candidate or "").strip()
        if not clean or clean in seen:
            return
        seen.add(clean)
        candidates.append(clean)

    lines = [line.strip() for line in value.splitlines() if line.strip()]
    command_lines = [
        line
        for line in lines
        if any(keyword in line.lower() for keyword in ("schedule", "/post", "/publish", "tomorrow", "today"))
    ]

    for line in command_lines:
        add(line)
    if lines:
        add(lines[0])
    add(value)
    return candidates


def _date_from_numbers(
    parts: dict[str, str | None],
    reference: datetime,
    tz: ZoneInfo,
    hour: int,
    minute: int,
) -> datetime | None:
    return _safe_datetime(
        int(parts["year"] or reference.year),
        int(parts["month"] or reference.month),
        int(parts["day"] or reference.day),
        hour,
        minute,
        tz,
    )


def _valid_clock(hour: int, minute: int) -> bool:
    return 0 <= hour <= 23 and 0 <= minute <= 59


def _safe_datetime(year: int, month: int, day: int, hour: int, minute: int, tz: ZoneInfo) -> datetime | None:
    if not _valid_clock(hour, minute):
        return None
    try:
        return datetime(year, month, day, hour, minute, tzinfo=tz)
    except ValueError:
        return None


def _parse_time(hour_value: str | None, minute_value: str | None, ampm: str | None) -> tuple[int, int]:
    hour = int(hour_value or 0)
    minute = int(minute_value or 0)
    marker = (ampm or "").lower()
    if marker == "pm" and hour != 12:
        hour += 12
    elif marker == "am" and hour == 12:
        hour = 0
    return hour, minute
