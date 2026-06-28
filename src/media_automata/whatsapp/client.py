from __future__ import annotations

from typing import Any, Protocol
from uuid import uuid4

import httpx

from media_automata.config import Settings
from media_automata.schemas import MediaAttachment


class WhatsAppClient(Protocol):
    async def send_text(self, chat_id: str, text: str) -> dict:
        ...

    async def send_image(
        self,
        chat_id: str,
        *,
        image_url: str | None = None,
        image_base64: str | None = None,
        caption: str | None = None,
    ) -> dict:
        ...

    async def send_document(
        self,
        chat_id: str,
        *,
        document_url: str | None = None,
        document_base64: str | None = None,
        filename: str,
        caption: str | None = None,
    ) -> dict:
        ...

    async def get_session(self) -> dict:
        ...

    async def start_session(self) -> dict:
        ...

    async def fetch_message_media(self, chat_id: str, message_id: str) -> MediaAttachment | None:
        ...


class OpenWAClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.openwa_base_url.rstrip("/")
        self._resolved_session_id: str | None = None

    async def send_text(self, chat_id: str, text: str) -> dict:
        return await self._post_message("send-text", {"chatId": chat_id, "text": text})

    async def send_image(
        self,
        chat_id: str,
        *,
        image_url: str | None = None,
        image_base64: str | None = None,
        caption: str | None = None,
    ) -> dict:
        image = _media_payload(url=image_url, data_base64=image_base64)
        return await self._post_message("send-image", {"chatId": chat_id, "image": image, "caption": caption})

    async def send_document(
        self,
        chat_id: str,
        *,
        document_url: str | None = None,
        document_base64: str | None = None,
        filename: str,
        caption: str | None = None,
    ) -> dict:
        document = _media_payload(url=document_url, data_base64=document_base64)
        return await self._post_message(
            "send-document",
            {"chatId": chat_id, "document": document, "filename": filename, "caption": caption},
        )

    async def _post_message(self, endpoint: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=20) as client:
            session_id = await self._session_id(client)
            url = f"{self.base_url}/sessions/{session_id}/messages/{endpoint}"
            headers = self._headers(include_content_type=True)
            body = {key: value for key, value in payload.items() if value}
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            return response.json()

    async def get_session(self) -> dict:
        async with httpx.AsyncClient(timeout=20) as client:
            session_id = await self._session_id(client)
            url = f"{self.base_url}/sessions/{session_id}"
            headers = self._headers()
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()

    async def start_session(self) -> dict:
        async with httpx.AsyncClient(timeout=60) as client:
            session_id = await self._session_id(client)
            url = f"{self.base_url}/sessions/{session_id}/start"
            headers = self._headers()
            response = await client.post(url, headers=headers, json={})
            if response.status_code in {400, 409}:
                current = await client.get(
                    f"{self.base_url}/sessions/{session_id}",
                    headers=headers,
                )
                current.raise_for_status()
                return current.json()
            response.raise_for_status()
            return response.json()

    async def fetch_message_media(self, chat_id: str, message_id: str) -> MediaAttachment | None:
        async with httpx.AsyncClient(timeout=20) as client:
            session_id = await self._session_id(client)
            url = f"{self.base_url}/sessions/{session_id}/messages"
            headers = self._headers()
            params = {"chatId": chat_id, "limit": "100"}
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            payload = response.json()
        for item in _iter_history_messages(payload):
            ids = {
                str(value)
                for value in (item.get("id"), item.get("messageId"), item.get("message_id"), item.get("waMessageId"))
                if value
            }
            if message_id not in ids:
                continue
            return _media_attachment_from_message(item)
        return None

    async def _session_id(self, client: httpx.AsyncClient) -> str:
        if self._resolved_session_id:
            return self._resolved_session_id

        session_ref = self.settings.openwa_session_id.strip()
        if not session_ref:
            raise ValueError("OPENWA_SESSION_ID is required.")

        response = await client.get(f"{self.base_url}/sessions", headers=self._headers())
        response.raise_for_status()
        resolved_session_id = _resolve_session_id(response.json(), session_ref)
        if resolved_session_id and resolved_session_id != session_ref:
            self._resolved_session_id = resolved_session_id
            return resolved_session_id
        return session_ref

    def _headers(self, *, include_content_type: bool = False) -> dict[str, str]:
        if not self.settings.openwa_api_key:
            raise ValueError("OPENWA_API_KEY is required.")
        headers = {
            "X-API-Key": self.settings.openwa_api_key,
            "X-Request-ID": f"req_{uuid4().hex}",
        }
        if include_content_type:
            headers["Content-Type"] = "application/json"
        return headers


def build_whatsapp_client(settings: Settings) -> WhatsAppClient:
    return OpenWAClient(settings)


def _media_payload(*, url: str | None, data_base64: str | None) -> dict[str, str]:
    if url:
        return {"url": url}
    if data_base64:
        return {"base64": data_base64}
    raise ValueError("Either a media URL or base64 payload is required.")


def _iter_history_messages(payload: Any) -> list[dict[str, Any]]:
    raw_messages = payload.get("messages") if isinstance(payload, dict) else None
    if isinstance(raw_messages, list):
        return [item for item in raw_messages if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _resolve_session_id(payload: Any, session_ref: str) -> str | None:
    for item in _iter_sessions(payload):
        item_id = str(item.get("id") or "").strip()
        item_name = str(item.get("name") or "").strip()
        if session_ref == item_id or (item_name and session_ref == item_name):
            return item_id or None
    return None


def _iter_sessions(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("sessions", "data", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _media_attachment_from_message(message: dict[str, Any]) -> MediaAttachment | None:
    from media_automata.whatsapp.normalizer import _media_attachment_from_container

    metadata_value = message.get("metadata")
    metadata: dict[str, Any] = metadata_value if isinstance(metadata_value, dict) else {}
    attachment = _media_attachment_from_container(message)
    if attachment is None and metadata:
        attachment = _media_attachment_from_container(metadata)
    return attachment
