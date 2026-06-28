from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Platform(StrEnum):
    LINKEDIN = "linkedin"
    X = "x"
    INSTAGRAM = "instagram"


class JobMode(StrEnum):
    PUBLISH = "publish"
    DRAFT = "draft"
    SCHEDULE = "schedule"


class JobStatus(StrEnum):
    RECEIVED = "received"
    PARSED = "parsed"
    PLANNED = "planned"
    QUEUED = "queued"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class BrowserRunStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class ErrorCode(StrEnum):
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    CAPTCHA_OR_VERIFICATION = "CAPTCHA_OR_VERIFICATION"
    COMPOSER_NOT_FOUND = "COMPOSER_NOT_FOUND"
    MEDIA_UPLOAD_FAILED = "MEDIA_UPLOAD_FAILED"
    CONTENT_REJECTED = "CONTENT_REJECTED"
    PUBLISH_BUTTON_DISABLED = "PUBLISH_BUTTON_DISABLED"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    UNKNOWN_UI_STATE = "UNKNOWN_UI_STATE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class MediaAttachment(BaseModel):
    mimetype: str
    filename: str | None = None
    data_base64: str | None = None
    url: str | None = None


class IncomingWhatsAppMessage(BaseModel):
    message_id: str
    from_number: str
    chat_id: str
    body: str
    timestamp: int | None = None
    from_me: bool = False
    is_group: bool = False
    media: MediaAttachment | None = None
    quoted_message_id: str | None = None
    quoted_body: str | None = None
    quoted_media: MediaAttachment | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class Asset(BaseModel):
    id: str
    source: str
    mime_type: str
    filename: str | None = None
    storage_uri: str
    sha256: str
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    created_at: datetime | None = None


class CommandIntent(BaseModel):
    intent: Literal["publish", "schedule", "draft", "unknown"] = "unknown"
    mode: JobMode = JobMode.PUBLISH
    platforms: list[Platform] = Field(default_factory=list)
    account: str = "main_brand"
    topic: str = ""
    tone: str = "clear, concise"
    platform_instructions: dict[str, str] = Field(default_factory=dict)
    media_asset_ids: list[str] = Field(default_factory=list)
    scheduled_for: str | None = None
    instagram_targets: list[Literal["feed", "story", "reel"]] = Field(default_factory=list)
    target_job_id: str | None = None
    missing_fields: list[str] = Field(default_factory=list)

    @field_validator("platforms", mode="before")
    @classmethod
    def normalize_platforms(cls, value: Any) -> Any:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip().lower() for item in value.split(",") if item.strip()]
        return value


class ContentStrategy(BaseModel):
    positioning: str = ""
    audience: str = ""
    angle: str = ""
    cta: str = ""
    style_rules: list[str] = Field(default_factory=list)


class PlatformContent(BaseModel):
    platform: Platform
    text: str = ""
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    media_asset_ids: list[str] = Field(default_factory=list)
    mode: Literal["single", "thread", "feed", "reel", "story", "document"] = "single"
    posts: list[str] = Field(default_factory=list)
    posting_target: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @property
    def primary_text(self) -> str:
        return self.caption or self.text or "\n\n".join(self.posts)


class PlatformTaskPayload(BaseModel):
    job_id: str
    platform: Platform
    account: str
    mode: JobMode
    content: PlatformContent
    scheduled_for: datetime | None = None
    raw_intent: dict[str, Any] = Field(default_factory=dict)


class AgentPlan(BaseModel):
    intent: CommandIntent
    strategy: ContentStrategy
    platform_contents: list[PlatformContent]


class PlatformContentPlan(BaseModel):
    contents: list[PlatformContent]


class PlatformResult(BaseModel):
    platform: Platform
    status: Literal["success", "failed", "unknown"]
    result_url: str | None = None
    message: str = ""
    artifact_ids: list[str] = Field(default_factory=list)
    error_code: ErrorCode | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    status: Literal["success", "failed", "unknown"]
    confidence: float = 0.0
    result_url: str | None = None
    evidence: list[str] = Field(default_factory=list)
    failure_reason: str | None = None


class JobSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: JobStatus
    mode: JobMode
    raw_command: str
    parsed_intent: dict[str, Any] | None = None
    content_plan: dict[str, Any] | None = None
    scheduled_for: datetime | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class PlatformTaskSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    platform: Platform
    account_key: str
    status: TaskStatus
    task_payload: dict[str, Any]
    result: dict[str, Any] | None = None
    scheduled_for: datetime | None = None
    attempt_count: int = 0
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class JobDetail(BaseModel):
    job: JobSnapshot
    tasks: list[PlatformTaskSnapshot]


class MediaTodoStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
