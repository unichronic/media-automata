from __future__ import annotations

import httpx
import pytest

from media_automata.config import Settings
from media_automata.whatsapp.client import OpenWAClient, _resolve_session_id


class DummyResponse:
    def __init__(self, method: str, url: str, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self._request = httpx.Request(method, url)

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code} error",
                request=self._request,
                response=httpx.Response(self.status_code, request=self._request, json=self._payload),
            )


class DummyAsyncClient:
    def __init__(self, responses: list[DummyResponse]):
        self._responses = responses
        self.calls: list[tuple[str, str]] = []

    async def __aenter__(self) -> DummyAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str, **kwargs):
        self.calls.append(("GET", url))
        return self._responses.pop(0)

    async def post(self, url: str, **kwargs):
        self.calls.append(("POST", url))
        return self._responses.pop(0)


def test_resolve_session_id_matches_name_and_id() -> None:
    payload = [
        {"id": "uuid-1", "name": "main"},
        {"id": "uuid-2", "name": "backup"},
    ]

    assert _resolve_session_id(payload, "main") == "uuid-1"
    assert _resolve_session_id(payload, "uuid-2") == "uuid-2"
    assert _resolve_session_id(payload, "missing") is None


@pytest.mark.asyncio
async def test_get_session_resolves_named_session(monkeypatch: pytest.MonkeyPatch) -> None:
    client = DummyAsyncClient(
        [
            DummyResponse("GET", "http://openwa/api/sessions", 200, [{"id": "uuid-1", "name": "main"}]),
            DummyResponse("GET", "http://openwa/api/sessions/uuid-1", 200, {"id": "uuid-1", "status": "ready"}),
        ]
    )

    monkeypatch.setattr("media_automata.whatsapp.client.httpx.AsyncClient", lambda timeout: client)

    settings = Settings.model_validate(
        {
            "OPENWA_BASE_URL": "http://openwa/api",
            "OPENWA_API_KEY": "test-key",
            "OPENWA_SESSION_ID": "main",
        }
    )
    payload = await OpenWAClient(settings).get_session()

    assert payload["id"] == "uuid-1"
    assert client.calls == [
        ("GET", "http://openwa/api/sessions"),
        ("GET", "http://openwa/api/sessions/uuid-1"),
    ]


@pytest.mark.asyncio
async def test_get_session_uses_cached_resolved_session_id(monkeypatch: pytest.MonkeyPatch) -> None:
    client = DummyAsyncClient(
        [
            DummyResponse("GET", "http://openwa/api/sessions", 200, [{"id": "uuid-1", "name": "main"}]),
            DummyResponse("GET", "http://openwa/api/sessions/uuid-1", 200, {"id": "uuid-1", "status": "ready"}),
            DummyResponse("GET", "http://openwa/api/sessions/uuid-1", 200, {"id": "uuid-1", "status": "ready"}),
        ]
    )

    monkeypatch.setattr("media_automata.whatsapp.client.httpx.AsyncClient", lambda timeout: client)

    settings = Settings.model_validate(
        {
            "OPENWA_BASE_URL": "http://openwa/api",
            "OPENWA_API_KEY": "test-key",
            "OPENWA_SESSION_ID": "main",
        }
    )
    openwa = OpenWAClient(settings)

    await openwa.get_session()
    await openwa.get_session()

    assert client.calls == [
        ("GET", "http://openwa/api/sessions"),
        ("GET", "http://openwa/api/sessions/uuid-1"),
        ("GET", "http://openwa/api/sessions/uuid-1"),
    ]
