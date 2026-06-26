from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from media_automata.config import Settings
from media_automata.db import models, session_scope
from media_automata.db.models import Asset
from media_automata.platforms import build_platform_worker
from media_automata.repository import Repository
from media_automata.retry import exponential_backoff_seconds, is_retryable_error
from media_automata.schemas import BrowserRunStatus, ErrorCode, PlatformResult, PlatformTaskPayload, TaskStatus
from media_automata.storage import LocalStorage
from media_automata.whatsapp.client import build_whatsapp_client


@dataclass
class WorkerRunResult:
    claimed: bool
    task_id: str | None = None
    job_id: str | None = None
    status: str | None = None
    message: str = ""


class BrowserTaskRunner:
    MAX_AUTOMATIC_ATTEMPTS = 3

    def __init__(self, settings: Settings, worker_id: str | None = None):
        self.settings = settings
        self.worker_id = worker_id or f"worker_{uuid4().hex[:12]}"
        self.storage = LocalStorage(settings.storage_root)

    async def run_once(self, platform: str | None = None) -> WorkerRunResult:
        with session_scope() as session:
            repo = Repository(session, self.settings)
            task = repo.claim_next_task(self.worker_id, platform)
            if not task:
                return WorkerRunResult(claimed=False, message="No pending platform tasks.")

            payload = PlatformTaskPayload.model_validate(task.task_payload)
            payload = self._hydrate_payload_from_job_results(repo, payload)
            task.task_payload = payload.model_dump(mode="json")
            profile = None
            browser_run = None
            heartbeat_task: asyncio.Task[None] | None = None
            try:
                profile = repo.acquire_browser_profile_lock(payload.platform, payload.account, self.worker_id)
                heartbeat_task = asyncio.create_task(self._heartbeat_active_task(profile.id, task.id))
                browser_run = repo.create_browser_run(task, profile.id)
                repo.set_task_status(task, TaskStatus.RUNNING, {"worker_id": self.worker_id})
                repo.refresh_job_rollup(task.job_id)
                session.flush()
                chat_id = repo.get_job_chat_id(task.job_id)
                asset_lookup = self._asset_lookup(repo, payload.content.media_asset_ids)
                session.commit()
                if chat_id:
                    await self._send_text_safely(
                        chat_id, f"{payload.platform.value} started for account {payload.account}."
                    )

                worker = build_platform_worker(payload.platform, self.settings)
                context = self._worker_context(profile.profile_path)
                result = await worker.publish_post(payload, context, asset_lookup)
            except Exception as exc:
                result = PlatformResult(
                    platform=payload.platform,
                    status="failed",
                    message=f"Worker crashed: {exc}",
                )
            if heartbeat_task:
                heartbeat_task.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat_task

            artifact = self._save_result_artifact(
                repo,
                task.id,
                task.job_id,
                browser_run.id if browser_run else None,
                result,
            )
            result.artifact_ids.append(artifact.id)
            if profile and result.raw.get("auth_status"):
                auth_status = str(result.raw["auth_status"])
                auth_message = str(result.raw.get("auth_message") or result.message)
                if result.raw.get("runtime") == "android-native-uiautomator2":
                    repo.record_profile_native_auth_check(
                        profile,
                        auth_status=auth_status,
                        message=auth_message,
                    )
                else:
                    repo.record_profile_auth_check(
                        profile,
                        auth_status=auth_status,
                        message=auth_message,
                    )
            retry_scheduled = is_retryable_error(result.error_code) and task.attempt_count < self.MAX_AUTOMATIC_ATTEMPTS
            if retry_scheduled:
                delay_seconds = exponential_backoff_seconds(task.attempt_count)
                repo.schedule_task_retry(
                    task,
                    result,
                    scheduled_for=datetime.now(UTC) + timedelta(seconds=delay_seconds),
                )
            else:
                repo.complete_task(task, result)
            if browser_run:
                repo.complete_browser_run(
                    browser_run,
                    status=BrowserRunStatus.COMPLETED if result.status == "success" else BrowserRunStatus.FAILED,
                    error_message=None if result.status == "success" else result.message,
                )
            if profile:
                repo.release_browser_profile_lock(profile, self.worker_id)
            repo.refresh_job_rollup(task.job_id)
            chat_id = repo.get_job_chat_id(task.job_id)
            if chat_id:
                status = "completed" if result.status == "success" else "failed"
                await self._send_text_safely(
                    chat_id,
                    f"{payload.platform.value} {status} for account {payload.account}: {result.message}",
                )
            if self._needs_manual_login_alert(result):
                if chat_id:
                    await self._send_manual_login_alert(chat_id, payload, result)
            job = repo.get_job(task.job_id)
            if chat_id and job and job.status in {"completed", "failed"}:
                await self._send_text_safely(chat_id, f"Job {job.id} {job.status}.")
            return WorkerRunResult(
                claimed=True,
                task_id=task.id,
                job_id=task.job_id,
                status="retrying" if retry_scheduled else result.status,
                message=(
                    f"{result.message} Automatic retry scheduled for {task.scheduled_for.isoformat()}."
                    if retry_scheduled and task.scheduled_for
                    else result.message
                ),
            )

    async def run_loop(self, *, idle_sleep_seconds: float = 2.0) -> None:
        while True:
            result = await self.run_once()
            if not result.claimed:
                await asyncio.sleep(idle_sleep_seconds)

    async def _heartbeat_active_task(
        self,
        profile_id: str,
        task_id: str,
        *,
        interval_seconds: float = 30.0,
    ) -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            with session_scope() as session:
                repo = Repository(session, self.settings)
                profile_alive = repo.refresh_browser_profile_lock(profile_id, self.worker_id)
                task_alive = repo.refresh_task_heartbeat(task_id, self.worker_id)
                if not profile_alive or not task_alive:
                    return

    def _worker_context(self, profile_path: str):
        from pathlib import Path

        from media_automata.platforms.base import WorkerContext

        return WorkerContext(
            settings=self.settings,
            storage=self.storage,
            profile_path=Path(profile_path),
            artifact_root=self.settings.artifact_root,
        )

    @staticmethod
    def _asset_lookup(repo: Repository, asset_ids: list[str]) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for asset_id in asset_ids:
            asset = repo.session.get(Asset, asset_id)
            if asset:
                lookup[asset_id] = asset.storage_uri
        return lookup

    def _save_result_artifact(
        self,
        repo: Repository,
        task_id: str,
        job_id: str,
        browser_run_id: str | None,
        result: PlatformResult,
    ):
        storage_uri, _ = self.storage.save_text(
            result.model_dump_json(indent=2),
            filename=f"{task_id}-result.json",
            prefix="artifacts",
        )
        return repo.add_artifact(
            kind="platform_result",
            storage_uri=storage_uri,
            mime_type="application/json",
            job_id=job_id,
            platform_task_id=task_id,
            browser_run_id=browser_run_id,
        )

    @staticmethod
    def _hydrate_payload_from_job_results(repo: Repository, payload: PlatformTaskPayload) -> PlatformTaskPayload:
        if not (
            payload.platform.value == "instagram"
            and payload.content.mode == "story"
            and payload.content.extra.get("instagram_story_source") == "feed_post"
            and not payload.content.extra.get("instagram_post_url")
        ):
            return payload

        stmt = (
            select(models.PlatformTask)
            .where(
                models.PlatformTask.job_id == payload.job_id,
                models.PlatformTask.platform == "instagram",
                models.PlatformTask.status == TaskStatus.COMPLETED.value,
            )
            .order_by(models.PlatformTask.completed_at.desc())
        )
        for candidate in repo.session.scalars(stmt):
            candidate_payload = PlatformTaskPayload.model_validate(candidate.task_payload)
            result = candidate.result or {}
            result_url = str(result.get("result_url") or "").strip()
            if candidate_payload.content.mode in {"feed", "reel"} and result.get("status") == "success" and result_url:
                content = payload.content.model_copy(
                    update={"extra": {**payload.content.extra, "instagram_post_url": result_url}}
                )
                return payload.model_copy(update={"content": content})
        return payload

    @staticmethod
    def _needs_manual_login_alert(result: PlatformResult) -> bool:
        return result.error_code in {ErrorCode.LOGIN_REQUIRED, ErrorCode.CAPTCHA_OR_VERIFICATION}

    async def _send_manual_login_alert(
        self,
        chat_id: str,
        payload: PlatformTaskPayload,
        result: PlatformResult,
    ) -> None:
        try:
            await self._send_text_safely(
                chat_id,
                (
                    f"{payload.platform.value} needs manual login for account {payload.account}.\n"
                    f"Reason: {result.message}\n"
                    f"Profile: {self.settings.browser_profile_root / payload.platform.value / payload.account}"
                ),
            )
        except Exception:
            return

    async def _send_text_safely(self, chat_id: str, text: str) -> None:
        try:
            whatsapp = build_whatsapp_client(self.settings)
            await whatsapp.send_text(chat_id, text)
        except Exception:
            return
