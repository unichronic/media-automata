from __future__ import annotations

from media_automata.schemas import PlatformResult, PlatformTaskPayload


def task_started_text(payload: PlatformTaskPayload) -> str:
    return f"{payload.platform.value} started for account {payload.account}."


def task_completed_text(payload: PlatformTaskPayload, result: PlatformResult) -> str:
    status = "completed" if result.status == "success" else "failed"
    return f"{payload.platform.value} {status} for account {payload.account}: {result.message}"


def final_job_text(job_id: str, status: str) -> str:
    return f"Job {job_id} {status}."
