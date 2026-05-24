from __future__ import annotations

from media_automata.schemas import JobStatus, TaskStatus

ALLOWED_JOB_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.RECEIVED: {JobStatus.PARSED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.PARSED: {JobStatus.PLANNED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.PLANNED: {JobStatus.QUEUED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.QUEUED: {JobStatus.EXECUTING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.EXECUTING: {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: {JobStatus.QUEUED, JobStatus.CANCELLED},
    JobStatus.CANCELLED: set(),
}

ALLOWED_TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.CLAIMED, TaskStatus.FAILED, TaskStatus.RETRYING},
    TaskStatus.CLAIMED: {TaskStatus.RUNNING, TaskStatus.FAILED},
    TaskStatus.RUNNING: {TaskStatus.VERIFYING, TaskStatus.COMPLETED, TaskStatus.FAILED},
    TaskStatus.VERIFYING: {TaskStatus.COMPLETED, TaskStatus.FAILED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: {TaskStatus.RETRYING},
    TaskStatus.RETRYING: {TaskStatus.PENDING, TaskStatus.FAILED},
}


def assert_job_transition(current: str, next_status: JobStatus) -> None:
    current_status = JobStatus(current)
    if next_status == current_status:
        return
    if next_status not in ALLOWED_JOB_TRANSITIONS[current_status]:
        raise ValueError(f"Invalid job transition: {current_status} -> {next_status}")


def assert_task_transition(current: str, next_status: TaskStatus) -> None:
    current_status = TaskStatus(current)
    if next_status == current_status:
        return
    if next_status not in ALLOWED_TASK_TRANSITIONS[current_status]:
        raise ValueError(f"Invalid task transition: {current_status} -> {next_status}")

