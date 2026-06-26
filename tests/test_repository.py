from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from media_automata.config import Settings
from media_automata.db.models import Base, PlatformTask
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


def test_claim_next_task_is_atomic_across_workers(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'claims.sqlite3'}",
        connect_args={"check_same_thread": False, "timeout": 10},
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    with factory() as session:
        repo = Repository(session, Settings())
        repo.create_platform_task(
            PlatformTaskPayload(
                job_id="job_atomic",
                platform=Platform.X,
                account="main_brand",
                mode=JobMode.PUBLISH,
                content=PlatformContent(platform=Platform.X, text="only once"),
            )
        )
        session.commit()

    barrier = Barrier(2)

    def claim(worker_id: str) -> str | None:
        with factory() as session:
            barrier.wait()
            task = Repository(session, Settings()).claim_next_task(worker_id)
            session.commit()
            return task.id if task else None

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed_ids = list(pool.map(claim, ("worker_a", "worker_b")))

    assert sum(task_id is not None for task_id in claimed_ids) == 1


def test_schedule_task_retry_defers_retryable_task() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        repo = Repository(session, Settings())
        task = repo.create_platform_task(
            PlatformTaskPayload(
                job_id="job_retry",
                platform=Platform.LINKEDIN,
                account="main_brand",
                mode=JobMode.PUBLISH,
                content=PlatformContent(platform=Platform.LINKEDIN, text="retry me"),
            )
        )
        claimed = repo.claim_next_task("worker_1")
        assert claimed is not None
        repo.set_task_status(claimed, TaskStatus.RUNNING)
        retry_at = datetime.now(UTC) + timedelta(minutes=1)

        from media_automata.schemas import ErrorCode, PlatformResult

        repo.schedule_task_retry(
            claimed,
            PlatformResult(
                platform=Platform.LINKEDIN,
                status="failed",
                message="temporary network issue",
                error_code=ErrorCode.NETWORK_TIMEOUT,
            ),
            scheduled_for=retry_at,
        )

        assert task.status == TaskStatus.PENDING.value
        assert task.scheduled_for == retry_at
        assert task.claimed_by is None
        assert task.heartbeat_at is None
        assert repo.claim_next_task("worker_2") is None


def test_fail_interrupted_tasks_releases_profiles_and_fails_active_jobs() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        repo = Repository(session, Settings())
        job = repo.create_job(requested_by_user_id=None, whatsapp_message_id=None, raw_command="/post hello")
        payload = PlatformTaskPayload(
            job_id=job.id,
            platform=Platform.X,
            account="main_brand",
            mode=JobMode.PUBLISH,
            content=PlatformContent(platform=Platform.X, text="hello"),
        )
        task = repo.create_platform_task(payload)
        profile = repo.acquire_browser_profile_lock(Platform.X, "main_brand", "dead-worker")
        repo.set_job_status(job, JobStatus.PARSED)
        repo.set_job_status(job, JobStatus.PLANNED)
        repo.set_job_status(job, JobStatus.QUEUED)
        claimed = repo.claim_next_task("dead-worker")
        assert claimed is not None
        repo.set_task_status(claimed, TaskStatus.RUNNING)
        repo.refresh_job_rollup(job.id)

        assert repo.fail_interrupted_tasks() == 1

        assert task.status == TaskStatus.FAILED.value
        assert task.claimed_by is None
        assert task.result is not None
        assert task.result["raw"]["interrupted"] is True
        assert profile.lock_status == "unlocked"
        assert profile.locked_by is None
        recovered_job = repo.get_job(job.id)
        assert recovered_job is not None
        assert recovered_job.status == JobStatus.FAILED.value


def test_create_job_is_idempotent_under_concurrent_duplicate_delivery(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'webhooks.sqlite3'}",
        connect_args={"check_same_thread": False, "timeout": 10},
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    barrier = Barrier(2)

    def create() -> str:
        with factory() as session:
            barrier.wait()
            job = Repository(session, Settings()).create_job(
                requested_by_user_id=None,
                whatsapp_message_id="duplicate-message",
                raw_command="/post once",
            )
            session.commit()
            return job.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        job_ids = list(pool.map(lambda _: create(), range(2)))

    assert job_ids[0] == job_ids[1]


def test_scheduled_task_survives_database_reopen(tmp_path: Path) -> None:
    database_path = tmp_path / "restart.sqlite3"
    engine = create_engine(f"sqlite:///{database_path}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    due_at = datetime.now(UTC) + timedelta(seconds=30)

    with factory() as session:
        Repository(session, Settings()).create_platform_task(
            PlatformTaskPayload(
                job_id="job_restart",
                platform=Platform.X,
                account="main_brand",
                mode=JobMode.SCHEDULE,
                content=PlatformContent(platform=Platform.X, text="after restart"),
            ),
            scheduled_for=due_at,
        )
        session.commit()

    engine.dispose()
    reopened = create_engine(f"sqlite:///{database_path}", future=True)
    with Session(reopened) as session:
        repo = Repository(session, Settings())
        assert repo.claim_next_task("worker_before_due") is None
        task = session.query(PlatformTask).one()
        task.scheduled_for = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
        claimed = repo.claim_next_task("worker_after_restart")
        assert claimed is not None
        assert claimed.job_id == "job_restart"
