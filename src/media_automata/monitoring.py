from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, or_, select

from media_automata.config import Settings
from media_automata.db import init_db, models, session_scope
from media_automata.platforms.base import WorkerContext
from media_automata.platforms.instagram_native import InstagramNativeWorker
from media_automata.repository import Repository
from media_automata.schemas import Platform, TaskStatus
from media_automata.storage import LocalStorage
from media_automata.whatsapp.client import build_whatsapp_client

OPENWA_READY_STATES = {"ready", "connected", "authenticated", "online", "running"}
ACTIVE_TASK_STATUSES = (TaskStatus.CLAIMED.value, TaskStatus.RUNNING.value, TaskStatus.VERIFYING.value)


async def run_production_check(
    settings: Settings,
    *,
    recover_openwa: bool = False,
    deep_instagram: bool = False,
    account: str = "main_brand",
) -> dict[str, Any]:
    """Check the production dependencies without exposing configured secrets."""

    init_db()
    checks: dict[str, dict[str, Any]] = {
        "database": _database_check(),
        "runtime_paths": _runtime_paths_check(settings),
        "queue": _queue_check(),
        "accounts": _account_cache_check(settings, account),
        "instagram_native_backup": _instagram_native_backup_check(account),
        "openwa": await check_openwa_session(settings, recover=recover_openwa),
    }
    if deep_instagram:
        checks["instagram_native"] = await check_instagram_native(settings, account=account)

    return {
        "status": _overall_status(checks),
        "generated_at": datetime.now(UTC).isoformat(),
        "checks": checks,
    }


async def check_openwa_session(settings: Settings, *, recover: bool = False) -> dict[str, Any]:
    if not settings.openwa_api_key:
        return _check(
            "fail",
            "OPENWA_API_KEY is not configured.",
            session_id=settings.openwa_session_id,
            recovered=False,
        )

    client = build_whatsapp_client(settings)
    try:
        payload = await client.get_session()
    except Exception as exc:
        return _check(
            "fail",
            f"OpenWA session lookup failed: {_safe_exception(exc)}",
            session_id=settings.openwa_session_id,
            recovered=False,
        )

    state = openwa_session_state(payload)
    if openwa_session_ready(payload):
        return _check(
            "ok",
            "OpenWA session is ready.",
            session_id=settings.openwa_session_id,
            state=state,
            recovered=False,
        )

    if not recover:
        return _check(
            "warn",
            "OpenWA session is not ready.",
            session_id=settings.openwa_session_id,
            state=state,
            recovered=False,
        )

    try:
        start_payload = await client.start_session()
    except Exception as exc:
        return _check(
            "fail",
            f"OpenWA session is not ready and start failed: {_safe_exception(exc)}",
            session_id=settings.openwa_session_id,
            state=state,
            recovered=False,
        )

    start_state = openwa_session_state(start_payload)
    for _ in range(10):
        await asyncio.sleep(3)
        try:
            payload = await client.get_session()
        except Exception as exc:
            return _check(
                "fail",
                f"OpenWA session start was requested, but follow-up lookup failed: {_safe_exception(exc)}",
                session_id=settings.openwa_session_id,
                state=start_state,
                recovered=False,
            )
        state = openwa_session_state(payload)
        if openwa_session_ready(payload):
            return _check(
                "ok",
                "OpenWA session was recovered and is ready.",
                session_id=settings.openwa_session_id,
                state=state,
                recovered=True,
            )

    return _check(
        "warn",
        "OpenWA session start was requested, but the session did not reach ready state yet.",
        session_id=settings.openwa_session_id,
        state=state or start_state,
        recovered=False,
    )


async def check_instagram_native(settings: Settings, *, account: str = "main_brand") -> dict[str, Any]:
    worker_id = "production_instagram_native_check"
    storage = LocalStorage(settings.storage_root)
    with session_scope() as session:
        repo = Repository(session, settings)
        try:
            profile = repo.acquire_browser_profile_lock(Platform.INSTAGRAM, account, worker_id)
        except RuntimeError as exc:
            return _check("warn", str(exc), account=account)

        context = WorkerContext(
            settings=settings,
            storage=storage,
            profile_path=Path(profile.profile_path),
            artifact_root=settings.artifact_root,
        )
        try:
            session.commit()
            runtime_result = await InstagramNativeWorker().check_runtime(context)
            if runtime_result.status != "success":
                return _check(
                    "fail",
                    runtime_result.message,
                    account=account,
                    runtime=runtime_result.raw.get("runtime"),
                    auth_status=runtime_result.raw.get("auth_status"),
                    error_code=runtime_result.error_code.value if runtime_result.error_code else None,
                )

            auth_result = await InstagramNativeWorker().check_auth(context, account=account)
            auth_status = str(auth_result.raw.get("auth_status") or auth_result.status)
            repo.record_profile_native_auth_check(profile, auth_status=auth_status, message=auth_result.message)
            if auth_status == "authenticated":
                return _check("ok", auth_result.message, account=account, auth_status=auth_status)
            return _check(
                "fail",
                auth_result.message,
                account=account,
                auth_status=auth_status,
                error_code=auth_result.error_code.value if auth_result.error_code else None,
            )
        finally:
            repo.release_browser_profile_lock(profile, worker_id)


def openwa_session_ready(payload: Any) -> bool:
    state = _normalize_openwa_state(openwa_session_state(payload))
    return state in OPENWA_READY_STATES


def openwa_session_state(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("status", "state", "sessionStatus", "connectionState", "connection_state"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for key in ("session", "data", "result"):
        value = payload.get(key)
        if isinstance(value, dict):
            nested = openwa_session_state(value)
            if nested:
                return nested
    return None


def _database_check() -> dict[str, Any]:
    try:
        with session_scope() as session:
            job_count = int(session.scalar(select(func.count()).select_from(models.Job)) or 0)
            task_count = int(session.scalar(select(func.count()).select_from(models.PlatformTask)) or 0)
        return _check("ok", "Database is reachable.", jobs=job_count, platform_tasks=task_count)
    except Exception as exc:
        return _check("fail", f"Database check failed: {_safe_exception(exc)}")


def _runtime_paths_check(settings: Settings) -> dict[str, Any]:
    try:
        paths = {
            "storage_root": settings.storage_root,
            "artifact_root": settings.artifact_root,
            "browser_profile_root": settings.browser_profile_root,
        }
        missing_or_unwritable: dict[str, str] = {}
        for name, path in paths.items():
            path.mkdir(parents=True, exist_ok=True)
            if not path.exists() or not path.is_dir():
                missing_or_unwritable[name] = str(path)
                continue
            probe = path / ".production-write-check"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        if missing_or_unwritable:
            return _check("fail", "One or more runtime paths are not writable.", paths=missing_or_unwritable)
        return _check("ok", "Runtime storage paths are writable.", paths={k: str(v) for k, v in paths.items()})
    except Exception as exc:
        return _check("fail", f"Runtime path check failed: {_safe_exception(exc)}")


def _queue_check() -> dict[str, Any]:
    try:
        now = datetime.now(UTC)
        stale_before = now - timedelta(minutes=30)
        with session_scope() as session:
            pending_due = int(
                session.scalar(
                    select(func.count())
                    .select_from(models.PlatformTask)
                    .where(
                        models.PlatformTask.status == TaskStatus.PENDING.value,
                        or_(models.PlatformTask.scheduled_for.is_(None), models.PlatformTask.scheduled_for <= now),
                    )
                )
                or 0
            )
            pending_scheduled = int(
                session.scalar(
                    select(func.count())
                    .select_from(models.PlatformTask)
                    .where(
                        models.PlatformTask.status == TaskStatus.PENDING.value,
                        models.PlatformTask.scheduled_for.is_not(None),
                        models.PlatformTask.scheduled_for > now,
                    )
                )
                or 0
            )
            active = int(
                session.scalar(
                    select(func.count())
                    .select_from(models.PlatformTask)
                    .where(models.PlatformTask.status.in_(ACTIVE_TASK_STATUSES))
                )
                or 0
            )
            stale_active = int(
                session.scalar(
                    select(func.count())
                    .select_from(models.PlatformTask)
                    .where(
                        models.PlatformTask.status.in_(ACTIVE_TASK_STATUSES),
                        models.PlatformTask.heartbeat_at.is_not(None),
                        models.PlatformTask.heartbeat_at < stale_before,
                    )
                )
                or 0
            )
        status = "warn" if stale_active else "ok"
        message = "Queue is healthy." if not stale_active else "Queue has stale active tasks."
        return _check(
            status,
            message,
            pending_due=pending_due,
            pending_scheduled=pending_scheduled,
            active=active,
            stale_active=stale_active,
        )
    except Exception as exc:
        return _check("fail", f"Queue check failed: {_safe_exception(exc)}")


def _account_cache_check(settings: Settings, account: str) -> dict[str, Any]:
    try:
        with session_scope() as session:
            repo = Repository(session, settings)
            for platform in (Platform.LINKEDIN, Platform.X, Platform.INSTAGRAM):
                repo.ensure_browser_profile(platform, account)
            profiles = repo.list_browser_profiles(account)
            items = [
                {
                    "platform": profile.platform,
                    "status": profile.status,
                    "lock_status": profile.lock_status,
                    "last_login_check_at": profile.last_login_check_at.isoformat()
                    if profile.last_login_check_at
                    else None,
                    "native_status": (profile.metadata_json or {}).get("native_last_auth_status")
                    if profile.platform == Platform.INSTAGRAM.value
                    else None,
                    "native_last_login_check_at": (profile.metadata_json or {}).get("native_last_login_check_at")
                    if profile.platform == Platform.INSTAGRAM.value
                    else None,
                    "credential_fallback_configured": bool(settings.platform_login_credentials(profile.platform)),
                }
                for profile in profiles
            ]
    except Exception as exc:
        return _check("fail", f"Account profile cache check failed: {_safe_exception(exc)}", account=account)

    unauthenticated = [
        item
        for item in items
        if item["status"] not in {"authenticated", "unknown"} or item.get("native_status") in {"login_required"}
    ]
    if unauthenticated:
        return _check("warn", "One or more account profiles need attention.", account=account, profiles=items)
    return _check("ok", "Account profile cache is present.", account=account, profiles=items)


def _instagram_native_backup_check(account: str) -> dict[str, Any]:
    latest_backup = Path("runtime/android-backups") / f"instagram-{account}-latest.tar.gz"
    if latest_backup.exists():
        return _check(
            "ok",
            "Latest Instagram Android app-data backup is present.",
            account=account,
            latest_backup=str(latest_backup),
            size_bytes=latest_backup.stat().st_size,
        )
    return _check(
        "warn",
        "Latest Instagram Android app-data backup is missing.",
        account=account,
        latest_backup=str(latest_backup),
    )


def _overall_status(checks: dict[str, dict[str, Any]]) -> str:
    statuses = {check.get("status") for check in checks.values()}
    if "fail" in statuses:
        return "failed"
    if "warn" in statuses:
        return "degraded"
    return "ok"


def _check(status: str, message: str, **fields: Any) -> dict[str, Any]:
    return {"status": status, "message": message, **fields}


def _normalize_openwa_state(value: str | None) -> str:
    return (value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _safe_exception(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{exc.response.status_code} {exc.response.reason_phrase}"
    return f"{type(exc).__name__}: {str(exc)[:300]}"
