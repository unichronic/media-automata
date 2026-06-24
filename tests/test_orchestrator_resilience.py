import base64
from typing import Any, cast

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from media_automata.config import Settings
from media_automata.db import models
from media_automata.db.models import Base
from media_automata.orchestrator import CommandOrchestrator
from media_automata.schemas import (
    AgentPlan,
    CommandIntent,
    ContentStrategy,
    IncomingWhatsAppMessage,
    JobMode,
    JobStatus,
    MediaAttachment,
    Platform,
    PlatformContent,
)


class StubGraph:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, _: str, *, media_asset_ids: list[str]) -> AgentPlan:
        self.calls += 1
        return AgentPlan(
            intent=CommandIntent(
                intent="publish",
                mode=JobMode.PUBLISH,
                platforms=[Platform.X],
                media_asset_ids=media_asset_ids,
            ),
            strategy=ContentStrategy(),
            platform_contents=[
                PlatformContent(platform=Platform.X, text="hello", media_asset_ids=media_asset_ids)
            ],
        )


class StubWhatsApp:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_text(self, _: str, text: str) -> None:
        self.messages.append(text)

    async def fetch_message_media(self, _: str, __: str):
        return None


@pytest.mark.asyncio
async def test_duplicate_whatsapp_delivery_does_not_replan(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    graph = StubGraph()
    whatsapp = StubWhatsApp()
    message = IncomingWhatsAppMessage(
        message_id="same-message",
        from_number="919999999999",
        chat_id="group@g.us",
        body="/post Twitter - hello",
    )

    with Session(engine) as session:
        orchestrator = CommandOrchestrator(
            settings=Settings(),
            session=session,
            agent_graph=cast(Any, graph),
            whatsapp=cast(Any, whatsapp),
        )
        first = await orchestrator.process_whatsapp_message(message)
        session.commit()
        second = await orchestrator.process_whatsapp_message(message)
        session.commit()

        assert first.job_id == second.job_id
        assert graph.calls == 1
        assert session.scalar(select(func.count()).select_from(models.Job)) == 1
        assert session.scalar(select(func.count()).select_from(models.PlatformTask)) == 1


@pytest.mark.asyncio
async def test_invalid_base64_media_creates_failed_job(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    graph = StubGraph()
    whatsapp = StubWhatsApp()
    message = IncomingWhatsAppMessage(
        message_id="bad-media",
        from_number="919999999999",
        chat_id="group@g.us",
        body="/post this photo to x",
        media=MediaAttachment(
            mimetype="image/jpeg",
            filename="bad.jpg",
            data_base64=base64.b64encode(b"not-an-image").decode(),
        ),
    )

    with Session(engine) as session:
        outcome = await CommandOrchestrator(
            settings=Settings(),
            session=session,
            agent_graph=cast(Any, graph),
            whatsapp=cast(Any, whatsapp),
        ).process_whatsapp_message(message)
        session.commit()
        job = session.scalar(select(models.Job).where(models.Job.id == outcome.job_id))

        assert outcome.handled is True
        assert job is not None
        assert job.status == JobStatus.QUEUED.value
        assert graph.calls == 1


@pytest.mark.asyncio
async def test_malformed_base64_media_is_recorded_as_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    graph = StubGraph()
    whatsapp = StubWhatsApp()
    message = IncomingWhatsAppMessage(
        message_id="malformed-base64",
        from_number="919999999999",
        chat_id="group@g.us",
        body="/post this photo to instagram",
        media=MediaAttachment(
            mimetype="image/jpeg",
            filename="bad.jpg",
            data_base64="not-valid-***",
        ),
    )

    with Session(engine) as session:
        outcome = await CommandOrchestrator(
            settings=Settings(),
            session=session,
            agent_graph=cast(Any, graph),
            whatsapp=cast(Any, whatsapp),
        ).process_whatsapp_message(message)
        session.commit()
        job = session.scalar(select(models.Job).where(models.Job.id == outcome.job_id))

        assert outcome.handled is True
        assert job is not None
        assert job.status == JobStatus.FAILED.value
        assert graph.calls == 0
        assert "media could not be processed" in outcome.message
