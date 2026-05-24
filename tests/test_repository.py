from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from media_automata.config import Settings
from media_automata.db.models import Base
from media_automata.repository import Repository
from media_automata.schemas import JobMode, JobStatus, Platform, PlatformContent, PlatformTaskPayload, TaskStatus


def test_claim_next_task_marks_task_claimed() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        repo = Repository(session, Settings())
        payload = PlatformTaskPayload(
            job_id="job_1",
            platform=Platform.LINKEDIN,
            account="main_brand",
            mode=JobMode.PUBLISH,
            content=PlatformContent(platform=Platform.LINKEDIN, text="hello"),
        )
        repo.create_platform_task(payload)

        task = repo.claim_next_task("worker_1")

        assert task is not None
        assert task.status == TaskStatus.CLAIMED.value
        assert task.claimed_by == "worker_1"
        assert task.attempt_count == 1


def test_claim_next_task_skips_future_scheduled_task() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        repo = Repository(session, Settings())
        future_payload = PlatformTaskPayload(
            job_id="job_1",
            platform=Platform.X,
            account="main_brand",
            mode=JobMode.SCHEDULE,
            content=PlatformContent(platform=Platform.X, text="later"),
        )
        due_payload = PlatformTaskPayload(
            job_id="job_2",
            platform=Platform.LINKEDIN,
            account="main_brand",
            mode=JobMode.PUBLISH,
            content=PlatformContent(platform=Platform.LINKEDIN, text="now"),
        )
        repo.create_platform_task(future_payload, scheduled_for=datetime.now(UTC) + timedelta(days=1))
        due = repo.create_platform_task(due_payload)

        task = repo.claim_next_task("worker_1")

        assert task is not None
        assert task.id == due.id
        assert task.status == TaskStatus.CLAIMED.value


def test_retry_failed_tasks_reopens_failed_job_and_clears_stale_claim() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        repo = Repository(session, Settings())
        job = repo.create_job(requested_by_user_id=None, whatsapp_message_id=None, raw_command="/post hello")
        repo.set_job_status(job, JobStatus.PARSED)
        repo.set_job_status(job, JobStatus.PLANNED)
        repo.set_job_status(job, JobStatus.QUEUED)
        repo.set_job_status(job, JobStatus.EXECUTING)
        payload = PlatformTaskPayload(
            job_id=job.id,
            platform=Platform.LINKEDIN,
            account="main_brand",
            mode=JobMode.PUBLISH,
            content=PlatformContent(platform=Platform.LINKEDIN, text="hello"),
        )
        task = repo.create_platform_task(payload)
        repo.set_task_status(task, TaskStatus.CLAIMED)
        task.claimed_by = "worker_1"
        task.heartbeat_at = datetime.now(UTC)
        repo.set_task_status(task, TaskStatus.RUNNING)
        repo.set_task_status(task, TaskStatus.FAILED)
        repo.set_job_status(job, JobStatus.FAILED)

        retried = repo.retry_failed_tasks(job.id, Platform.LINKEDIN.value)

        assert retried == 1
        assert job.status == JobStatus.QUEUED.value
        assert job.completed_at is None
        assert task.status == TaskStatus.PENDING.value
        assert task.result is None
        assert task.completed_at is None
        assert task.claimed_by is None
        assert task.heartbeat_at is None


def test_native_auth_check_does_not_overwrite_web_profile_status() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        repo = Repository(session, Settings())
        profile = repo.ensure_browser_profile(Platform.INSTAGRAM, "main_brand")
        repo.record_profile_auth_check(profile, auth_status="authenticated", message="web ok")

        repo.record_profile_native_auth_check(
            profile,
            auth_status="challenge_required",
            message="native verification needed",
        )

        assert profile.status == "authenticated"
        assert profile.metadata_json["last_auth_status"] == "authenticated"
        assert profile.metadata_json["native_last_auth_status"] == "challenge_required"
        assert profile.metadata_json["native_last_auth_message"] == "native verification needed"
