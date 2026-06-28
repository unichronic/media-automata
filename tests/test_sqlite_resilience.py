from unittest.mock import MagicMock

from sqlalchemy.exc import OperationalError

from media_automata.config import Settings
from media_automata.repository import Repository


def test_claim_next_task_retries_sqlite_lock(monkeypatch) -> None:
    repo = Repository(MagicMock(), Settings())
    attempts = {"count": 0}
    task = MagicMock()
    task.id = "task_1"
    task.job_id = "job_1"

    def flaky_claim(*_args, **_kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise OperationalError("UPDATE platform_tasks", {}, Exception("database is locked"))
        return "task_1"

    repo.session = MagicMock()
    repo.session.scalar.side_effect = flaky_claim
    repo.session.get.return_value = task
    repo.audit = MagicMock()
    monkeypatch.setattr("media_automata.repository.time.sleep", lambda _seconds: None)

    claimed = repo.claim_next_task("worker_1")

    assert claimed is task
    assert attempts["count"] == 2
    repo.session.rollback.assert_called_once()


def test_is_sqlite_locked_helper() -> None:
    from media_automata.worker import _is_sqlite_locked

    assert _is_sqlite_locked(OperationalError("stmt", {}, Exception("database is locked")))
    assert not _is_sqlite_locked(OperationalError("stmt", {}, Exception("no such table")))
