from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from media_automata.config import Settings
from media_automata.db import models
from media_automata.schemas import (
    Asset as AssetSchema,
)
from media_automata.schemas import (
    BrowserRunStatus,
    JobDetail,
    JobMode,
    JobSnapshot,
    JobStatus,
    Platform,
    PlatformResult,
    PlatformTaskPayload,
    PlatformTaskSnapshot,
    TaskStatus,
)
from media_automata.state import assert_job_transition, assert_task_transition

PROFILE_LOCK_STALE_AFTER = timedelta(minutes=30)


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class Repository:
    def __init__(self, session: Session, settings: Settings):
        self.session = session
        self.settings = settings

    def get_or_create_user_for_whatsapp(self, number: str, chat_id: str | None = None) -> models.User:
        user = self.session.scalar(select(models.User).where(models.User.primary_whatsapp_number == number))
        if user:
            if chat_id:
                contact = self.session.scalar(
                    select(models.WhatsAppContact).where(models.WhatsAppContact.whatsapp_number == number)
                )
                if contact:
                    contact.chat_id = chat_id
            return user
        user = models.User(primary_whatsapp_number=number, name=number)
        self.session.add(user)
        self.session.flush()
        contact = models.WhatsAppContact(user_id=user.id, whatsapp_number=number, chat_id=chat_id or number)
        self.session.add(contact)
        self.audit("user.created", {"user_id": user.id, "whatsapp_number": number})
        return user

    def ensure_browser_profile(self, platform: Platform | str, account_key: str) -> models.BrowserProfile:
        platform_value = str(platform)
        profile = self.session.scalar(
            select(models.BrowserProfile).where(
                models.BrowserProfile.platform == platform_value,
                models.BrowserProfile.account_key == account_key,
            )
        )
        if profile:
            return profile
        profile_path = self.settings.browser_profile_root / platform_value / account_key
        profile_path.mkdir(parents=True, exist_ok=True)
        profile = models.BrowserProfile(
            platform=platform_value,
            account_key=account_key,
            profile_path=str(profile_path),
            metadata_json={},
        )
        self.session.add(profile)
        self.session.flush()
        return profile

    def acquire_browser_profile_lock(
        self,
        platform: Platform | str,
        account_key: str,
        worker_id: str,
    ) -> models.BrowserProfile:
        profile = self.ensure_browser_profile(platform, account_key)
        if profile.lock_status == "locked" and profile.locked_by and profile.locked_by != worker_id:
            heartbeat_at = profile.lock_heartbeat_at
            is_stale = heartbeat_at is not None and utcnow() - aware_utc(heartbeat_at) > PROFILE_LOCK_STALE_AFTER
            if not is_stale:
                raise RuntimeError(f"Browser profile {profile.id} is locked by {profile.locked_by}")
        profile.lock_status = "locked"
        profile.locked_by = worker_id
        profile.lock_heartbeat_at = utcnow()
        self.session.flush()
        return profile

    def refresh_browser_profile_lock(self, profile_id: str, worker_id: str) -> bool:
        profile = self.session.get(models.BrowserProfile, profile_id)
        if not profile or profile.locked_by != worker_id:
            return False
        profile.lock_heartbeat_at = utcnow()
        self.session.flush()
        return True

    def release_browser_profile_lock(self, profile: models.BrowserProfile, worker_id: str) -> None:
        if profile.locked_by and profile.locked_by != worker_id:
            return
        profile.lock_status = "unlocked"
        profile.locked_by = None
        profile.lock_heartbeat_at = None
        profile.last_used_at = utcnow()
        self.session.flush()

    def record_profile_auth_check(
        self,
        profile: models.BrowserProfile,
        *,
        auth_status: str,
        message: str = "",
    ) -> None:
        status_map = {
            "authenticated": "authenticated",
            "login_required": "login_required",
            "challenge_required": "challenge_required",
            "failed": "auth_check_failed",
        }
        profile.status = status_map.get(auth_status, auth_status)
        profile.last_login_check_at = utcnow()
        profile.metadata_json = {
            **(profile.metadata_json or {}),
            "last_auth_status": auth_status,
            "last_auth_message": message,
        }
        self.session.flush()

    def record_profile_native_auth_check(
        self,
        profile: models.BrowserProfile,
        *,
        auth_status: str,
        message: str = "",
    ) -> None:
        profile.metadata_json = {
            **(profile.metadata_json or {}),
            "native_last_auth_status": auth_status,
            "native_last_auth_message": message,
            "native_last_login_check_at": utcnow().isoformat(),
        }
        self.session.flush()

    def list_browser_profiles(self, account_key: str | None = None) -> list[models.BrowserProfile]:
        stmt = select(models.BrowserProfile).order_by(
            models.BrowserProfile.platform.asc(),
            models.BrowserProfile.account_key.asc(),
        )
        if account_key:
            stmt = stmt.where(models.BrowserProfile.account_key == account_key)
        return list(self.session.scalars(stmt).all())

    def create_asset(
        self,
        *,
        source: str,
        mime_type: str,
        filename: str | None,
        storage_uri: str,
        sha256: str,
        width: int | None = None,
        height: int | None = None,
        duration_seconds: float | None = None,
    ) -> models.Asset:
        existing = self.session.scalar(select(models.Asset).where(models.Asset.sha256 == sha256))
        if existing:
            if width is not None:
                existing.width = width
            if height is not None:
                existing.height = height
            if duration_seconds is not None:
                existing.duration_seconds = duration_seconds
            return existing
        asset = models.Asset(
            source=source,
            mime_type=mime_type,
            filename=filename,
            storage_uri=storage_uri,
            sha256=sha256,
            width=width,
            height=height,
            duration_seconds=duration_seconds,
        )
        self.session.add(asset)
        self.session.flush()
        return asset

    def asset_schema(self, asset: models.Asset) -> AssetSchema:
        return AssetSchema(
            id=asset.id,
            source=asset.source,
            mime_type=asset.mime_type,
            filename=asset.filename,
            storage_uri=asset.storage_uri,
            sha256=asset.sha256,
            width=asset.width,
            height=asset.height,
            duration_seconds=asset.duration_seconds,
            created_at=asset.created_at,
        )

    def create_job(
        self,
        *,
        requested_by_user_id: str | None,
        whatsapp_message_id: str | None,
        raw_command: str,
        mode: JobMode = JobMode.PUBLISH,
        scheduled_for: datetime | None = None,
    ) -> models.Job:
        if whatsapp_message_id:
            existing = self.session.scalar(
                select(models.Job).where(models.Job.whatsapp_message_id == whatsapp_message_id)
            )
            if existing:
                return existing
        job = models.Job(
            requested_by_user_id=requested_by_user_id,
            whatsapp_message_id=whatsapp_message_id,
            status=JobStatus.RECEIVED.value,
            mode=mode.value,
            raw_command=raw_command,
            scheduled_for=scheduled_for,
        )
        self.session.add(job)
        self.session.flush()
        self.audit("job.created", {"job_id": job.id}, job_id=job.id)
        return job

    def set_job_status(self, job: models.Job, status: JobStatus, payload: dict[str, Any] | None = None) -> None:
        assert_job_transition(job.status, status)
        previous = job.status
        job.status = status.value
        job.updated_at = utcnow()
        if status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            job.completed_at = utcnow()
        else:
            job.completed_at = None
        self.audit("job.status_changed", {"from": previous, "to": status.value, **(payload or {})}, job_id=job.id)

    def set_job_intent(self, job: models.Job, parsed_intent: dict[str, Any], mode: JobMode) -> None:
        job.parsed_intent = parsed_intent
        job.mode = mode.value
        self.set_job_status(job, JobStatus.PARSED)

    def set_job_content_plan(self, job: models.Job, content_plan: dict[str, Any]) -> None:
        job.content_plan = content_plan
        self.set_job_status(job, JobStatus.PLANNED)

    def set_job_scheduled_for(self, job: models.Job, scheduled_for: datetime | None) -> None:
        job.scheduled_for = scheduled_for
        job.updated_at = utcnow()

    def create_platform_task(
        self,
        payload: PlatformTaskPayload,
        *,
        scheduled_for: datetime | None = None,
    ) -> models.PlatformTask:
        task_scheduled_for = scheduled_for or payload.scheduled_for
        if task_scheduled_for:
            payload = payload.model_copy(update={"scheduled_for": task_scheduled_for})
        task = models.PlatformTask(
            job_id=payload.job_id,
            platform=payload.platform.value,
            account_key=payload.account,
            status=TaskStatus.PENDING.value,
            task_payload=payload.model_dump(mode="json"),
            scheduled_for=task_scheduled_for,
        )
        self.session.add(task)
        self.session.flush()
        self.audit("task.created", {"platform": task.platform}, job_id=task.job_id, platform_task_id=task.id)
        return task

    def claim_next_task(self, worker_id: str, platform: str | None = None) -> models.PlatformTask | None:
        now = utcnow()
        stmt = select(models.PlatformTask).where(
            models.PlatformTask.status == TaskStatus.PENDING.value,
            or_(models.PlatformTask.scheduled_for.is_(None), models.PlatformTask.scheduled_for <= now),
        )
        if platform:
            stmt = stmt.where(models.PlatformTask.platform == platform)
        stmt = stmt.order_by(models.PlatformTask.created_at.asc()).limit(1)
        task = self.session.scalar(stmt)
        if not task:
            return None
        self.set_task_status(task, TaskStatus.CLAIMED, {"worker_id": worker_id})
        task.claimed_by = worker_id
        task.heartbeat_at = utcnow()
        task.attempt_count += 1
        self.session.flush()
        return task

    def set_task_status(
        self,
        task: models.PlatformTask,
        status: TaskStatus,
        payload: dict[str, Any] | None = None,
    ) -> None:
        assert_task_transition(task.status, status)
        previous = task.status
        task.status = status.value
        task.updated_at = utcnow()
        if status in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
            task.completed_at = utcnow()
        self.audit(
            "task.status_changed",
            {"from": previous, "to": status.value, **(payload or {})},
            job_id=task.job_id,
            platform_task_id=task.id,
        )

    def refresh_task_heartbeat(self, task_id: str, worker_id: str) -> bool:
        task = self.session.get(models.PlatformTask, task_id)
        if not task or task.claimed_by != worker_id:
            return False
        task.heartbeat_at = utcnow()
        self.session.flush()
        return True

    def complete_task(self, task: models.PlatformTask, result: PlatformResult) -> None:
        task.result = result.model_dump(mode="json")
        self.set_task_status(task, TaskStatus.COMPLETED if result.status == "success" else TaskStatus.FAILED)
        task.claimed_by = None
        task.heartbeat_at = None

    def retry_failed_tasks(self, job_id: str, platform: str | None = None) -> int:
        stmt = select(models.PlatformTask).where(
            models.PlatformTask.job_id == job_id,
            models.PlatformTask.status == TaskStatus.FAILED.value,
        )
        if platform:
            stmt = stmt.where(models.PlatformTask.platform == platform)
        count = 0
        for task in self.session.scalars(stmt).all():
            self.set_task_status(task, TaskStatus.RETRYING)
            self.set_task_status(task, TaskStatus.PENDING)
            task.result = None
            task.completed_at = None
            task.claimed_by = None
            task.heartbeat_at = None
            count += 1
        if count:
            job = self.get_job(job_id)
            if job and job.status == JobStatus.FAILED.value:
                self.set_job_status(job, JobStatus.QUEUED, {"retried_tasks": count})
        return count

    def create_browser_run(self, task: models.PlatformTask, profile_id: str | None) -> models.BrowserRun:
        run = models.BrowserRun(platform_task_id=task.id, profile_id=profile_id, status=BrowserRunStatus.STARTED.value)
        self.session.add(run)
        self.session.flush()
        return run

    def complete_browser_run(
        self,
        run: models.BrowserRun,
        *,
        status: BrowserRunStatus,
        error_message: str | None = None,
        screenshot_uri: str | None = None,
        trace_uri: str | None = None,
        console_log_uri: str | None = None,
    ) -> None:
        run.status = status.value
        run.error_message = error_message
        run.screenshot_uri = screenshot_uri
        run.trace_uri = trace_uri
        run.console_log_uri = console_log_uri
        run.completed_at = utcnow()

    def add_artifact(
        self,
        *,
        kind: str,
        storage_uri: str,
        mime_type: str | None = None,
        job_id: str | None = None,
        platform_task_id: str | None = None,
        browser_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> models.Artifact:
        artifact = models.Artifact(
            job_id=job_id,
            platform_task_id=platform_task_id,
            browser_run_id=browser_run_id,
            kind=kind,
            storage_uri=storage_uri,
            mime_type=mime_type,
            metadata_json=metadata or {},
        )
        self.session.add(artifact)
        self.session.flush()
        return artifact

    def get_artifact(self, artifact_id: str) -> models.Artifact | None:
        return self.session.get(models.Artifact, artifact_id)

    def list_artifacts_for_job(self, job_id: str) -> list[models.Artifact]:
        return list(
            self.session.scalars(
                select(models.Artifact)
                .where(models.Artifact.job_id == job_id)
                .order_by(models.Artifact.created_at.asc())
            )
        )

    def get_job(self, job_id: str) -> models.Job | None:
        return self.session.get(models.Job, job_id)

    def list_jobs(
        self,
        *,
        status: str | None = None,
        platform: str | None = None,
        limit: int = 50,
    ) -> list[models.Job]:
        stmt = select(models.Job).order_by(models.Job.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(models.Job.status == status)
        if platform:
            task_job_ids = select(models.PlatformTask.job_id).where(models.PlatformTask.platform == platform)
            stmt = stmt.where(models.Job.id.in_(task_job_ids))
        return list(self.session.scalars(stmt).all())

    def count_active_jobs(self) -> int:
        active_statuses = {
            JobStatus.RECEIVED.value,
            JobStatus.PARSED.value,
            JobStatus.PLANNED.value,
            JobStatus.QUEUED.value,
            JobStatus.EXECUTING.value,
        }
        jobs = self.session.scalars(select(models.Job.id).where(models.Job.status.in_(active_statuses))).all()
        return len(jobs)

    def get_job_chat_id(self, job_id: str) -> str | None:
        job = self.get_job(job_id)
        if not job or not job.requested_by_user_id:
            return None
        contact = self.session.scalar(
            select(models.WhatsAppContact).where(models.WhatsAppContact.user_id == job.requested_by_user_id)
        )
        if not contact:
            return None
        return contact.chat_id or contact.whatsapp_number

    def get_task(self, task_id: str) -> models.PlatformTask | None:
        return self.session.get(models.PlatformTask, task_id)

    def list_tasks_for_job(self, job_id: str) -> list[models.PlatformTask]:
        return list(
            self.session.scalars(
                select(models.PlatformTask)
                .where(models.PlatformTask.job_id == job_id)
                .order_by(models.PlatformTask.created_at.asc())
            )
        )

    def get_job_detail(self, job_id: str) -> JobDetail | None:
        job = self.get_job(job_id)
        if not job:
            return None
        return JobDetail(
            job=JobSnapshot.model_validate(job),
            tasks=[PlatformTaskSnapshot.model_validate(task) for task in self.list_tasks_for_job(job_id)],
        )

    def refresh_job_rollup(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if not job:
            return
        tasks = self.list_tasks_for_job(job_id)
        if not tasks:
            return
        statuses = {TaskStatus(task.status) for task in tasks}
        if TaskStatus.FAILED in statuses and all(s in {TaskStatus.FAILED, TaskStatus.COMPLETED} for s in statuses):
            if job.status != JobStatus.FAILED.value:
                self.set_job_status(job, JobStatus.FAILED)
        elif statuses == {TaskStatus.COMPLETED}:
            if job.status != JobStatus.COMPLETED.value:
                if job.status == JobStatus.QUEUED.value:
                    self.set_job_status(job, JobStatus.EXECUTING)
                self.set_job_status(job, JobStatus.COMPLETED)
        elif any(s in {TaskStatus.CLAIMED, TaskStatus.RUNNING, TaskStatus.VERIFYING} for s in statuses):
            if job.status == JobStatus.QUEUED.value:
                self.set_job_status(job, JobStatus.EXECUTING)

    def audit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        job_id: str | None = None,
        platform_task_id: str | None = None,
    ) -> None:
        self.session.add(
            models.AuditEvent(
                job_id=job_id,
                platform_task_id=platform_task_id,
                event_type=event_type,
                event_payload=payload,
            )
        )
