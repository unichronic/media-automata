from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from media_automata.config import Settings
from media_automata.db.models import Base
from media_automata.orchestrator import (
    _extract_job_ref,
    _extract_platform,
    _extract_todo_ref,
    _normalize_job_ref,
    _normalize_todo_ref,
    _parse_account_key,
    _parse_todo_add,
    _todo_detail,
    _todo_line,
)
from media_automata.repository import Repository
from media_automata.schemas import JobMode, MediaTodoStatus, Platform


def test_parse_todo_add_defaults_to_all_platforms() -> None:
    title, platforms = _parse_todo_add("/todo add Launch post")
    assert title == "Launch post"
    assert platforms == [Platform.LINKEDIN, Platform.X, Platform.INSTAGRAM]


def test_parse_todo_add_reads_trailing_platforms() -> None:
    title, platforms = _parse_todo_add("/todo add Launch post linkedin x")
    assert title == "Launch post"
    assert platforms == [Platform.LINKEDIN, Platform.X]


def test_extract_refs_and_normalize() -> None:
    assert _extract_todo_ref("/todo check todo_abc123 linkedin") == "todo_abc123"
    assert _normalize_todo_ref("abc123") == "todo_abc123"
    assert _extract_job_ref("/status job_abc123def456") == "job_abc123def456"
    assert _extract_job_ref("/retry abc123 x") == "abc123"
    assert _normalize_job_ref("abc123") == "job_abc123"


def test_extract_platform_and_account_key() -> None:
    assert _extract_platform("/todo check todo_abc twitter") == "x"
    assert _parse_account_key("/accounts") == "main_brand"
    assert _parse_account_key("/accounts alt_brand") == "alt_brand"


def test_media_todo_lifecycle() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        repo = Repository(session, Settings())
        todo = repo.create_media_todo("Launch post", [Platform.LINKEDIN, Platform.X], notes="draft")

        assert todo.title == "Launch post"
        assert todo.platforms == ["linkedin", "x"]
        assert "linkedin:pending" in _todo_line(todo)

        repo.check_media_todo_platform(todo.id, Platform.LINKEDIN)
        assert "linkedin:done" in _todo_line(todo)
        assert "pending" in _todo_detail(todo)

        repo.check_media_todo_platform(todo.id, Platform.X)
        assert todo.status == MediaTodoStatus.COMPLETED.value
        assert "[DONE]" in _todo_line(todo)


def test_resolve_job_and_todo_prefix() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        repo = Repository(session, Settings())
        job = repo.create_job(requested_by_user_id=None, whatsapp_message_id=None, raw_command="/post hello")
        todo = repo.create_media_todo("Launch", [Platform.LINKEDIN])

        assert repo.resolve_job(job.id[:12]) is not None
        assert repo.resolve_media_todo(todo.id[:12]) is not None
