from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from media_automata.agents.graph import SocialAgentGraph
from media_automata.config import Settings
from media_automata.media import inspect_media, validate_media_size
from media_automata.repository import Repository
from media_automata.scheduling import is_future_schedule, parse_scheduled_for
from media_automata.schemas import (
    AgentPlan,
    IncomingWhatsAppMessage,
    JobMode,
    JobStatus,
    MediaAttachment,
    Platform,
    PlatformContent,
    PlatformTaskPayload,
)
from media_automata.storage import LocalStorage
from media_automata.whatsapp.client import WhatsAppClient

MAX_CONCURRENT_JOBS = 3
KILL_SWITCH_PATH = Path("runtime/KILL_SWITCH")
MEDIA_REFERENCE_PATTERNS = (
    re.compile(r"\b(?:post|share|upload)\s+this\b", re.IGNORECASE),
    re.compile(r"\bthis\s+(?:photo|image|pic|picture|media|video)\b", re.IGNORECASE),
    re.compile(r"\b(?:quoted|replied|attached)\s+(?:photo|image|pic|picture|media|video)\b", re.IGNORECASE),
)


@dataclass
class CommandOutcome:
    handled: bool
    job_id: str | None = None
    message: str = ""


class CommandOrchestrator:
    def __init__(
        self,
        *,
        settings: Settings,
        session: Session,
        agent_graph: SocialAgentGraph,
        whatsapp: WhatsAppClient,
    ):
        self.settings = settings
        self.repo = Repository(session, settings)
        self.agent_graph = agent_graph
        self.whatsapp = whatsapp
        self.storage = LocalStorage(settings.storage_root)

    async def process_whatsapp_message(self, message: IncomingWhatsAppMessage) -> CommandOutcome:
        if message.from_me and not self._is_command(message.body):
            return CommandOutcome(handled=False, message="Ignored outbound non-command WhatsApp message.")
        if not self._is_authorized(message.from_number):
            return CommandOutcome(handled=False, message="Sender is not authorized.")
        if not self._is_command(message.body):
            return CommandOutcome(handled=False, message="Message does not match a command prefix.")

        if message.body.lower().startswith("/status"):
            return await self._handle_status(message)
        if message.body.lower().startswith("/retry"):
            return await self._handle_retry(message)
        if message.body.lower().startswith("/accounts"):
            return await self._handle_accounts(message)

        if KILL_SWITCH_PATH.exists():
            text = "Publishing is paused by the local kill switch."
            await self._send_text_safely(message.chat_id, text)
            return CommandOutcome(handled=True, message=text)

        active_jobs = self.repo.count_active_jobs()
        if active_jobs >= MAX_CONCURRENT_JOBS:
            text = f"System is busy with {active_jobs} active job(s). Try again after the current jobs finish."
            await self._send_text_safely(message.chat_id, text)
            return CommandOutcome(handled=True, message=text)

        user = self.repo.get_or_create_user_for_whatsapp(message.from_number, chat_id=message.chat_id)
        asset_ids = await self._store_message_media(message)
        job = self.repo.create_job(
            requested_by_user_id=user.id,
            whatsapp_message_id=message.message_id,
            raw_command=message.body,
            mode=JobMode.PUBLISH,
        )

        if job.status != JobStatus.RECEIVED.value:
            detail = self.repo.get_job_detail(job.id)
            text = f"Job {job.id} already exists with status {detail.job.status if detail else job.status}."
            await self._send_text_safely(message.chat_id, text)
            return CommandOutcome(handled=True, job_id=job.id, message=text)

        plan = await self.agent_graph.run(message.body, media_asset_ids=asset_ids)
        self.repo.set_job_intent(job, plan.intent.model_dump(mode="json"), plan.intent.mode)

        if plan.intent.intent not in {"publish", "draft", "schedule"}:
            self.repo.set_job_status(job, JobStatus.FAILED, {"reason": f"Unsupported intent: {plan.intent.intent}"})
            text = f"Job {job.id} failed: unsupported intent {plan.intent.intent}."
            await self._send_text_safely(message.chat_id, text)
            return CommandOutcome(handled=True, job_id=job.id, message=text)

        if plan.intent.missing_fields:
            self.repo.set_job_status(job, JobStatus.FAILED, {"missing_fields": plan.intent.missing_fields})
            text = f"Job {job.id} needs more information: {', '.join(plan.intent.missing_fields)}."
            await self._send_text_safely(message.chat_id, text)
            return CommandOutcome(handled=True, job_id=job.id, message=text)

        if not asset_ids and _expects_media_from_context(message.body):
            publishable_contents = [
                content for content in plan.platform_contents if not _content_requires_input_media(content)
            ]
            if not publishable_contents:
                self.repo.set_job_status(job, JobStatus.FAILED, {"reason": "expected_media_not_received"})
                text = (
                    f"Job {job.id} failed: I could not read the quoted or attached media from WhatsApp. "
                    "Send the image again with the command as its caption, or retry after the gateway reconnects."
                )
                await self._send_text_safely(message.chat_id, text)
                return CommandOutcome(handled=True, job_id=job.id, message=text)
            if len(publishable_contents) != len(plan.platform_contents):
                plan = plan.model_copy(update={"platform_contents": publishable_contents})

        self.repo.set_job_content_plan(job, self._content_plan_payload(plan))

        scheduled_for = None
        if plan.intent.intent == "schedule" or plan.intent.mode == JobMode.SCHEDULE:
            scheduled_for = parse_scheduled_for(plan.intent.scheduled_for, message.body)
            if not scheduled_for:
                self.repo.set_job_status(job, JobStatus.FAILED, {"reason": "scheduled_for_not_parsed"})
                text = f"Job {job.id} failed: I could not parse the scheduled time."
                await self._send_text_safely(message.chat_id, text)
                return CommandOutcome(handled=True, job_id=job.id, message=text)
            if not is_future_schedule(scheduled_for):
                self.repo.set_job_status(job, JobStatus.FAILED, {"reason": "scheduled_for_in_past"})
                text = f"Job {job.id} failed: scheduled time is in the past."
                await self._send_text_safely(message.chat_id, text)
                return CommandOutcome(handled=True, job_id=job.id, message=text)
            self.repo.set_job_scheduled_for(job, scheduled_for)

        for content in plan.platform_contents:
            payload = PlatformTaskPayload(
                job_id=job.id,
                platform=content.platform,
                account=plan.intent.account,
                mode=plan.intent.mode,
                content=content,
                scheduled_for=scheduled_for,
                raw_intent=plan.intent.model_dump(mode="json"),
            )
            self.repo.ensure_browser_profile(content.platform, plan.intent.account)
            self.repo.create_platform_task(payload, scheduled_for=scheduled_for)

        self.repo.set_job_status(job, JobStatus.QUEUED)
        text = self._job_created_text(job.id, plan, scheduled_for=scheduled_for)
        await self._send_text_safely(message.chat_id, text)
        return CommandOutcome(handled=True, job_id=job.id, message=text)

    async def _handle_status(self, message: IncomingWhatsAppMessage) -> CommandOutcome:
        job_id = _extract_job_id(message.body)
        if not job_id:
            text = "Send `/status job_<id>`."
            await self._send_text_safely(message.chat_id, text)
            return CommandOutcome(handled=True, message=text)
        detail = self.repo.get_job_detail(job_id)
        if not detail:
            text = f"Job {job_id} was not found."
        else:
            lines = [f"Job {detail.job.id}: {detail.job.status}"]
            for task in detail.tasks:
                lines.append(f"- {task.platform}: {task.status}")
            text = "\n".join(lines)
        await self._send_text_safely(message.chat_id, text)
        return CommandOutcome(handled=True, job_id=job_id, message=text)

    async def _handle_retry(self, message: IncomingWhatsAppMessage) -> CommandOutcome:
        job_id = _extract_job_id(message.body)
        platform = _extract_retry_platform(message.body)
        if not job_id:
            text = "Send `/retry job_<id>` or `/retry job_<id> x`."
            await self._send_text_safely(message.chat_id, text)
            return CommandOutcome(handled=True, message=text)
        retried = self.repo.retry_failed_tasks(job_id, platform)
        job = self.repo.get_job(job_id)
        if job and retried:
            self.repo.set_job_status(job, JobStatus.QUEUED)
        text = f"Queued {retried} failed task(s) for retry on job {job_id}."
        await self._send_text_safely(message.chat_id, text)
        return CommandOutcome(handled=True, job_id=job_id, message=text)

    async def _handle_accounts(self, message: IncomingWhatsAppMessage) -> CommandOutcome:
        account_key = _extract_account_key(message.body) or "main_brand"
        platforms = ("linkedin", "x", "instagram")
        for platform in platforms:
            self.repo.ensure_browser_profile(platform, account_key)

        profiles = {profile.platform: profile for profile in self.repo.list_browser_profiles(account_key)}
        lines = [f"Account `{account_key}` profile status:"]
        for platform in platforms:
            profile = profiles[platform]
            credentials = "configured" if self.settings.platform_login_credentials(platform) else "missing"
            checked_at = profile.last_login_check_at.isoformat() if profile.last_login_check_at else "never"
            native_status = ""
            if platform == Platform.INSTAGRAM.value:
                metadata = profile.metadata_json or {}
                native_checked_at = metadata.get("native_last_login_check_at") or "never"
                native_status = (
                    f"; native {metadata.get('native_last_auth_status') or 'unknown'}; "
                    f"native checked {native_checked_at}"
                )
            lines.append(
                f"- {platform}: {profile.status}; lock {profile.lock_status}; "
                f"credentials {credentials}; checked {checked_at}{native_status}"
            )
            lines.append(f"  path: {profile.profile_path}")

        text = "\n".join(lines)
        await self._send_text_safely(message.chat_id, text)
        return CommandOutcome(handled=True, message=text)

    async def _send_text_safely(self, chat_id: str, text: str) -> None:
        try:
            await self.whatsapp.send_text(chat_id, text)
        except Exception:
            return

    async def _store_message_media(self, message: IncomingWhatsAppMessage) -> list[str]:
        attachments: list[tuple[MediaAttachment, str]] = []
        if message.media:
            attachments.append((message.media, "whatsapp"))
        quoted_media = message.quoted_media
        if not quoted_media and message.quoted_message_id:
            try:
                quoted_media = await self.whatsapp.fetch_message_media(message.chat_id, message.quoted_message_id)
            except Exception:
                quoted_media = None
        if quoted_media:
            attachments.append((quoted_media, "whatsapp_quoted"))

        asset_ids: list[str] = []
        seen: set[str] = set()
        for attachment, source in attachments:
            asset_id = await self._store_media_attachment(attachment, source=source)
            if asset_id and asset_id not in seen:
                seen.add(asset_id)
                asset_ids.append(asset_id)
        return asset_ids

    async def _store_media_attachment(self, attachment: MediaAttachment, *, source: str) -> str | None:
        data = await self._media_attachment_bytes(attachment)
        if data is None:
            return None
        validate_media_size(data, attachment.mimetype)
        metadata = inspect_media(data, attachment.mimetype)
        filename = attachment.filename or "whatsapp-media"
        storage_uri, digest = self.storage.save_bytes(
            data,
            filename=filename,
            prefix="assets",
            mime_type=attachment.mimetype,
        )
        asset = self.repo.create_asset(
            source=source,
            mime_type=attachment.mimetype,
            filename=attachment.filename,
            storage_uri=storage_uri,
            sha256=digest,
            width=metadata.width,
            height=metadata.height,
            duration_seconds=metadata.duration_seconds,
        )
        return asset.id

    async def _media_attachment_bytes(self, attachment: MediaAttachment) -> bytes | None:
        if attachment.data_base64:
            return base64.b64decode(attachment.data_base64)
        if not attachment.url:
            return None
        async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
            response = await client.get(attachment.url)
            response.raise_for_status()
            return response.content

    def _is_authorized(self, number: str) -> bool:
        allowed = self.settings.allowed_numbers
        return "*" in allowed or number in allowed

    def _is_command(self, body: str) -> bool:
        stripped = body.strip().lower()
        return any(stripped.startswith(prefix.lower()) for prefix in self.settings.prefixes)

    @staticmethod
    def _content_plan_payload(plan: AgentPlan) -> dict:
        return {
            "strategy": plan.strategy.model_dump(mode="json"),
            "platform_contents": [content.model_dump(mode="json") for content in plan.platform_contents],
        }

    @staticmethod
    def _job_created_text(job_id: str, plan: AgentPlan, *, scheduled_for=None) -> str:
        if scheduled_for:
            lines = [f"Job {job_id} scheduled for {scheduled_for.isoformat()}.", "", "Platforms:"]
        else:
            lines = [f"Job {job_id} queued.", "", "Platforms:"]
        for content in plan.platform_contents:
            destination = ""
            if content.platform.value == "instagram" and content.mode in {"feed", "story", "reel"}:
                destination = f" {content.mode}"
                if content.mode == "story":
                    story_source = content.extra.get("instagram_story_source", "media")
                    source_label = "feed-post share" if story_source == "feed_post" else "direct media"
                    destination = f" story ({source_label})"
            lines.append(f"- {content.platform.value}{destination}: queued")
        return "\n".join(lines)


def _extract_job_id(text: str) -> str | None:
    match = re.search(r"\bjob_[a-f0-9]+\b", text)
    return match.group(0) if match else None


def _extract_retry_platform(text: str) -> str | None:
    lower = text.lower()
    for platform in ("linkedin", "instagram"):
        if platform in lower:
            return platform
    if re.search(r"\bx\b", lower) or "twitter" in lower:
        return "x"
    return None


def _expects_media_from_context(text: str) -> bool:
    return any(pattern.search(text) for pattern in MEDIA_REFERENCE_PATTERNS)


def _content_requires_input_media(content: PlatformContent) -> bool:
    if content.platform != Platform.INSTAGRAM:
        return False
    if content.mode == "story" and content.extra.get("instagram_story_source") == "feed_post":
        return False
    return content.mode in {"feed", "story", "reel"}


def _extract_account_key(text: str) -> str | None:
    match = re.search(r"\baccount\s*[:=]\s*([a-zA-Z0-9_.-]+)", text)
    if match:
        return match.group(1)
    for token in text.strip().split()[1:]:
        clean = token.strip()
        if clean.lower() not in {"status", "profiles", "profile"}:
            return clean
    return None
