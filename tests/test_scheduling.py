from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from media_automata.scheduling import is_future_schedule, parse_scheduled_for


def test_parse_month_first_schedule_without_year() -> None:
    now = datetime(2026, 5, 19, 20, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    scheduled_for = parse_scheduled_for("schedule this for May 26 12 PM", now=now)

    assert scheduled_for == datetime(2026, 5, 26, 6, 30, tzinfo=UTC)


def test_user_command_schedule_takes_precedence_over_llm_iso_guess() -> None:
    now = datetime(2026, 5, 24, 20, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    scheduled_for = parse_scheduled_for(
        "/post schedule this for all 3 platforms at May 26 12 PM",
        "2026-05-26T12:00:00+00:00",
        now=now,
    )

    assert scheduled_for == datetime(2026, 5, 26, 6, 30, tzinfo=UTC)


def test_parse_relative_schedule() -> None:
    now = datetime(2026, 5, 19, 20, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    scheduled_for = parse_scheduled_for("tomorrow 9:30am", now=now)

    assert scheduled_for == datetime(2026, 5, 20, 4, 0, tzinfo=UTC)


def test_is_future_schedule() -> None:
    now = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)

    assert is_future_schedule(datetime(2026, 5, 19, 12, 1, tzinfo=UTC), now=now)
    assert not is_future_schedule(datetime(2026, 5, 19, 11, 59, tzinfo=UTC), now=now)


def test_same_day_past_time_does_not_roll_to_next_year() -> None:
    now = datetime(2026, 5, 20, 17, 48, tzinfo=ZoneInfo("Asia/Kolkata"))

    scheduled_for = parse_scheduled_for("may 20 17:45", now=now)

    assert scheduled_for is not None
    assert scheduled_for == datetime(2026, 5, 20, 12, 15, tzinfo=UTC)
    assert not is_future_schedule(scheduled_for, now=now.astimezone(UTC))
