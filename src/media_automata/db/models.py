from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from media_automata.ids import new_id
from media_automata.schemas import BrowserRunStatus, JobMode, JobStatus, TaskStatus


def now_utc() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_utc,
        onupdate=now_utc,
        nullable=False,
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("user"))
    name: Mapped[str | None] = mapped_column(String(255))
    primary_whatsapp_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(64), default="operator")


class WhatsAppContact(Base, TimestampMixin):
    __tablename__ = "whatsapp_contacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("wa"))
    user_id: Mapped[str | None] = mapped_column(String(64), index=True)
    whatsapp_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    chat_id: Mapped[str | None] = mapped_column(String(128), index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))


class Account(Base, TimestampMixin):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("platform", "account_key", name="uq_account_platform_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("acct"))
    owner_user_id: Mapped[str | None] = mapped_column(String(64), index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    account_key: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    default_profile_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(64), default="active")


class BrowserProfile(Base, TimestampMixin):
    __tablename__ = "browser_profiles"
    __table_args__ = (UniqueConstraint("platform", "account_key", name="uq_profile_platform_account"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("profile"))
    platform: Mapped[str] = mapped_column(String(32), index=True)
    account_key: Mapped[str] = mapped_column(String(128), index=True)
    profile_path: Mapped[str] = mapped_column(Text)
    lock_status: Mapped[str] = mapped_column(String(32), default="unlocked", index=True)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    lock_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(64), default="unknown")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Asset(Base, TimestampMixin):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("asset"))
    source: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(128))
    filename: Mapped[str | None] = mapped_column(String(512))
    storage_uri: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("job"))
    requested_by_user_id: Mapped[str | None] = mapped_column(String(64), index=True)
    whatsapp_message_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default=JobStatus.RECEIVED.value, index=True)
    mode: Mapped[str] = mapped_column(String(32), default=JobMode.PUBLISH.value)
    raw_command: Mapped[str] = mapped_column(Text)
    parsed_intent: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    content_plan: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformTask(Base, TimestampMixin):
    __tablename__ = "platform_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("task"))
    job_id: Mapped[str] = mapped_column(String(64), index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    account_key: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default=TaskStatus.PENDING.value, index=True)
    task_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    claimed_by: Mapped[str | None] = mapped_column(String(128), index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BrowserRun(Base, TimestampMixin):
    __tablename__ = "browser_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("run"))
    platform_task_id: Mapped[str] = mapped_column(String(64), index=True)
    profile_id: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default=BrowserRunStatus.STARTED.value)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trace_uri: Mapped[str | None] = mapped_column(Text)
    screenshot_uri: Mapped[str | None] = mapped_column(Text)
    console_log_uri: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)


class AgentMessage(Base, TimestampMixin):
    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("agentmsg"))
    job_id: Mapped[str | None] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(64))
    node: Mapped[str | None] = mapped_column(String(128), index=True)
    content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Artifact(Base, TimestampMixin):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("artifact"))
    job_id: Mapped[str | None] = mapped_column(String(64), index=True)
    platform_task_id: Mapped[str | None] = mapped_column(String(64), index=True)
    browser_run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    storage_uri: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(128))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("audit"))
    job_id: Mapped[str | None] = mapped_column(String(64), index=True)
    platform_task_id: Mapped[str | None] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    event_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class MediaTodo(Base, TimestampMixin):
    __tablename__ = "media_todos"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("todo"))
    title: Mapped[str] = mapped_column(String(512))
    notes: Mapped[str | None] = mapped_column(Text)
    platforms: Mapped[list[str]] = mapped_column(JSON)
    completed_platforms: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    job_id: Mapped[str | None] = mapped_column(String(64), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
