import pytest

from media_automata.schemas import JobStatus, TaskStatus
from media_automata.state import assert_job_transition, assert_task_transition


def test_job_transition_allows_happy_path() -> None:
    assert_job_transition(JobStatus.RECEIVED.value, JobStatus.PARSED)
    assert_job_transition(JobStatus.PARSED.value, JobStatus.PLANNED)
    assert_job_transition(JobStatus.PLANNED.value, JobStatus.QUEUED)
    assert_job_transition(JobStatus.QUEUED.value, JobStatus.EXECUTING)
    assert_job_transition(JobStatus.EXECUTING.value, JobStatus.COMPLETED)


def test_job_transition_rejects_completed_to_queued() -> None:
    with pytest.raises(ValueError, match="Invalid job transition"):
        assert_job_transition(JobStatus.COMPLETED.value, JobStatus.QUEUED)


def test_task_transition_allows_retry_path() -> None:
    assert_task_transition(TaskStatus.FAILED.value, TaskStatus.RETRYING)
    assert_task_transition(TaskStatus.RETRYING.value, TaskStatus.PENDING)


def test_task_transition_rejects_pending_to_completed() -> None:
    with pytest.raises(ValueError, match="Invalid task transition"):
        assert_task_transition(TaskStatus.PENDING.value, TaskStatus.COMPLETED)
