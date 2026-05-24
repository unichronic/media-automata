from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from media_automata.agents import SocialAgentGraph, build_llm_provider
from media_automata.config import get_settings
from media_automata.db import init_db, session_scope
from media_automata.monitoring import check_openwa_session, run_production_check
from media_automata.orchestrator import CommandOrchestrator
from media_automata.platforms import build_platform_worker
from media_automata.platforms.base import WorkerContext
from media_automata.platforms.browser_use_worker import BrowserUsePlatformWorker
from media_automata.platforms.instagram_native import InstagramNativeWorker
from media_automata.repository import Repository
from media_automata.schemas import JobMode, Platform, PlatformContent, PlatformTaskPayload
from media_automata.storage import LocalStorage
from media_automata.whatsapp.client import build_whatsapp_client
from media_automata.whatsapp.normalizer import normalize_openwa_payload
from media_automata.worker import BrowserTaskRunner


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="Media Automata", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/deployment")
async def deployment_health(
    recover_openwa: bool = False,
    deep_instagram: bool = False,
    account: str = "main_brand",
) -> dict[str, Any]:
    return await run_production_check(
        get_settings(),
        recover_openwa=recover_openwa,
        deep_instagram=deep_instagram,
        account=account,
    )


@app.get("/whatsapp/session")
async def whatsapp_session_status() -> dict[str, Any]:
    whatsapp = build_whatsapp_client(get_settings())
    return await whatsapp.get_session()


@app.post("/whatsapp/session/recover")
async def whatsapp_session_recover() -> dict[str, Any]:
    return await check_openwa_session(get_settings(), recover=True)


@app.post("/webhooks/whatsapp")
async def whatsapp_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    message = normalize_openwa_payload(payload)
    with session_scope() as session:
        llm = build_llm_provider(settings)
        graph = SocialAgentGraph(llm)
        whatsapp = build_whatsapp_client(settings)
        orchestrator = CommandOrchestrator(
            settings=settings,
            session=session,
            agent_graph=graph,
            whatsapp=whatsapp,
        )
        outcome = await orchestrator.process_whatsapp_message(message)
        return {"handled": outcome.handled, "job_id": outcome.job_id, "message": outcome.message}


@app.get("/jobs")
def list_jobs(status: str | None = None, platform: str | None = None, limit: int = 50) -> dict[str, Any]:
    settings = get_settings()
    with session_scope() as session:
        repo = Repository(session, settings)
        jobs = repo.list_jobs(status=status, platform=platform, limit=min(max(limit, 1), 200))
        return {
            "jobs": [
                {
                    "id": job.id,
                    "status": job.status,
                    "mode": job.mode,
                    "raw_command": job.raw_command,
                    "scheduled_for": job.scheduled_for.isoformat() if job.scheduled_for else None,
                    "created_at": job.created_at.isoformat(),
                    "updated_at": job.updated_at.isoformat(),
                    "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                }
                for job in jobs
            ]
        }


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    settings = get_settings()
    with session_scope() as session:
        repo = Repository(session, settings)
        detail = repo.get_job_detail(job_id)
        if not detail:
            raise HTTPException(status_code=404, detail="Job not found")
        payload = detail.model_dump(mode="json")
        payload["artifacts"] = [_artifact_payload(artifact) for artifact in repo.list_artifacts_for_job(job_id)]
        return payload


@app.get("/jobs/{job_id}/artifacts")
def list_job_artifacts(job_id: str) -> dict[str, Any]:
    settings = get_settings()
    with session_scope() as session:
        repo = Repository(session, settings)
        if not repo.get_job(job_id):
            raise HTTPException(status_code=404, detail="Job not found")
        artifacts = [_artifact_payload(item) for item in repo.list_artifacts_for_job(job_id)]
        return {"job_id": job_id, "artifacts": artifacts}


@app.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str):
    settings = get_settings()
    storage = LocalStorage(settings.storage_root)
    with session_scope() as session:
        repo = Repository(session, settings)
        artifact = repo.get_artifact(artifact_id)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")
        path = storage.resolve(artifact.storage_uri)
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="Artifact file not found")
        return FileResponse(path, media_type=artifact.mime_type, filename=Path(path).name)


@app.get("/accounts")
def list_accounts(account: str = "main_brand") -> dict[str, Any]:
    settings = get_settings()
    platforms = ("linkedin", "x", "instagram")
    with session_scope() as session:
        repo = Repository(session, settings)
        for platform in platforms:
            repo.ensure_browser_profile(platform, account)
        profiles = repo.list_browser_profiles(account)
        return {
            "account": account,
            "profiles": [
                {
                    "platform": profile.platform,
                    "status": profile.status,
                    "lock_status": profile.lock_status,
                    "profile_path": profile.profile_path,
                    "last_login_check_at": profile.last_login_check_at.isoformat()
                    if profile.last_login_check_at
                    else None,
                    "native_status": (profile.metadata_json or {}).get("native_last_auth_status")
                    if profile.platform == Platform.INSTAGRAM.value
                    else None,
                    "native_last_login_check_at": (profile.metadata_json or {}).get("native_last_login_check_at")
                    if profile.platform == Platform.INSTAGRAM.value
                    else None,
                    "native_message": (profile.metadata_json or {}).get("native_last_auth_message")
                    if profile.platform == Platform.INSTAGRAM.value
                    else None,
                    "credential_fallback_configured": bool(settings.platform_login_credentials(profile.platform)),
                }
                for profile in profiles
            ],
        }


@app.post("/accounts/{platform}/login-check")
async def account_login_check(platform: Platform, account: str = "main_brand") -> dict[str, Any]:
    settings = get_settings()
    worker_id = "api_login_check"
    storage = LocalStorage(settings.storage_root)
    with session_scope() as session:
        repo = Repository(session, settings)
        profile = repo.acquire_browser_profile_lock(platform, account, worker_id)
        payload = PlatformTaskPayload(
            job_id="login_check",
            platform=platform,
            account=account,
            mode=JobMode.PUBLISH,
            content=PlatformContent(platform=platform),
        )
        context = WorkerContext(
            settings=settings,
            storage=storage,
            profile_path=Path(profile.profile_path),
            artifact_root=settings.artifact_root,
        )
        worker = build_platform_worker(platform, settings)
        if not isinstance(worker, BrowserUsePlatformWorker):
            raise HTTPException(status_code=400, detail="Platform does not support browser auth checks")
        try:
            session.commit()
            result = await worker.ensure_authenticated(payload, context)
            repo.record_profile_auth_check(profile, auth_status=result.status, message=result.message)
            return {
                "platform": platform.value,
                "account": account,
                "status": result.status,
                "message": result.message,
                "final_url": result.final_url,
            }
        finally:
            repo.release_browser_profile_lock(profile, worker_id)


@app.post("/accounts/instagram/native-check")
async def instagram_native_auth_check(account: str = "main_brand") -> dict[str, Any]:
    settings = get_settings()
    worker_id = "api_instagram_native_check"
    storage = LocalStorage(settings.storage_root)
    with session_scope() as session:
        repo = Repository(session, settings)
        profile = repo.acquire_browser_profile_lock(Platform.INSTAGRAM, account, worker_id)
        context = WorkerContext(
            settings=settings,
            storage=storage,
            profile_path=Path(profile.profile_path),
            artifact_root=settings.artifact_root,
        )
        try:
            session.commit()
            result = await InstagramNativeWorker().check_auth(context, account=account)
            auth_status = str(result.raw.get("auth_status") or result.status)
            repo.record_profile_native_auth_check(profile, auth_status=auth_status, message=result.message)
            return _native_account_result(account, result, auth_status)
        finally:
            repo.release_browser_profile_lock(profile, worker_id)


@app.post("/accounts/instagram/native-login")
async def instagram_native_login(account: str = "main_brand") -> dict[str, Any]:
    settings = get_settings()
    worker_id = "api_instagram_native_login"
    storage = LocalStorage(settings.storage_root)
    with session_scope() as session:
        repo = Repository(session, settings)
        profile = repo.acquire_browser_profile_lock(Platform.INSTAGRAM, account, worker_id)
        context = WorkerContext(
            settings=settings,
            storage=storage,
            profile_path=Path(profile.profile_path),
            artifact_root=settings.artifact_root,
        )
        try:
            session.commit()
            result = await InstagramNativeWorker().login(context, account=account)
            auth_status = str(result.raw.get("auth_status") or result.status)
            repo.record_profile_native_auth_check(profile, auth_status=auth_status, message=result.message)
            return _native_account_result(account, result, auth_status)
        finally:
            repo.release_browser_profile_lock(profile, worker_id)


@app.post("/accounts/instagram/native-backup")
async def instagram_native_backup(account: str = "main_brand") -> dict[str, Any]:
    settings = get_settings()
    worker_id = "api_instagram_native_backup"
    storage = LocalStorage(settings.storage_root)
    with session_scope() as session:
        repo = Repository(session, settings)
        profile = repo.acquire_browser_profile_lock(Platform.INSTAGRAM, account, worker_id)
        context = WorkerContext(
            settings=settings,
            storage=storage,
            profile_path=Path(profile.profile_path),
            artifact_root=settings.artifact_root,
        )
        try:
            session.commit()
            result = await InstagramNativeWorker().backup_app_data(context, account=account)
            auth_status = str(result.raw.get("auth_status") or result.status)
            repo.record_profile_native_auth_check(profile, auth_status=auth_status, message=result.message)
            return _native_account_result(account, result, auth_status)
        finally:
            repo.release_browser_profile_lock(profile, worker_id)


@app.post("/accounts/instagram/native-restore")
async def instagram_native_restore(account: str = "main_brand", backup_path: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    worker_id = "api_instagram_native_restore"
    storage = LocalStorage(settings.storage_root)
    with session_scope() as session:
        repo = Repository(session, settings)
        profile = repo.acquire_browser_profile_lock(Platform.INSTAGRAM, account, worker_id)
        context = WorkerContext(
            settings=settings,
            storage=storage,
            profile_path=Path(profile.profile_path),
            artifact_root=settings.artifact_root,
        )
        try:
            session.commit()
            result = await InstagramNativeWorker().restore_app_data(context, account=account, backup_path=backup_path)
            auth_status = str(result.raw.get("auth_status") or result.status)
            repo.record_profile_native_auth_check(profile, auth_status=auth_status, message=result.message)
            return _native_account_result(account, result, auth_status)
        finally:
            repo.release_browser_profile_lock(profile, worker_id)


def _artifact_payload(artifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "kind": artifact.kind,
        "job_id": artifact.job_id,
        "platform_task_id": artifact.platform_task_id,
        "browser_run_id": artifact.browser_run_id,
        "mime_type": artifact.mime_type,
        "storage_uri": artifact.storage_uri,
        "download_path": f"/artifacts/{artifact.id}/download",
        "created_at": artifact.created_at.isoformat(),
        "metadata": artifact.metadata_json,
    }


def _native_account_result(account: str, result, auth_status: str) -> dict[str, Any]:
    return {
        "platform": Platform.INSTAGRAM.value,
        "account": account,
        "status": result.status,
        "native_status": auth_status,
        "message": result.message,
        "error_code": result.error_code.value if result.error_code else None,
        "raw": result.raw,
    }


@app.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, platform: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    with session_scope() as session:
        repo = Repository(session, settings)
        job = repo.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        count = repo.retry_failed_tasks(job_id, platform)
        return {"job_id": job_id, "retried": count}


@app.post("/worker/run-once")
async def worker_run_once(platform: str | None = None) -> dict[str, Any]:
    runner = BrowserTaskRunner(get_settings())
    result = await runner.run_once(platform=platform)
    return {
        "claimed": result.claimed,
        "task_id": result.task_id,
        "job_id": result.job_id,
        "status": result.status,
        "message": result.message,
    }
