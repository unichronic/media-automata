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
        if not self.settings.openwa_api_key:
            raise ValueError("OPENWA_API_KEY is required.")
        url = f"{self.base_url}/sessions/{self.settings.openwa_session_id}/messages/{endpoint}"
        headers = {
            "X-API-Key": self.settings.openwa_api_key,
            "Content-Type": "application/json",
            "X-Request-ID": f"req_{uuid4().hex}",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            body = {key: value for key, value in payload.items() if value}
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            return response.json()

    async def get_session(self) -> dict:
        if not self.settings.openwa_api_key:
            raise ValueError("OPENWA_API_KEY is required.")
        url = f"{self.base_url}/sessions/{self.settings.openwa_session_id}"
        headers = {"X-API-Key": self.settings.openwa_api_key, "X-Request-ID": f"req_{uuid4().hex}"}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()

    async def start_session(self) -> dict:
        if not self.settings.openwa_api_key:
            raise ValueError("OPENWA_API_KEY is required.")
        url = f"{self.base_url}/sessions/{self.settings.openwa_session_id}/start"
        headers = {"X-API-Key": self.settings.openwa_api_key, "X-Request-ID": f"req_{uuid4().hex}"}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, headers=headers, json={})
            if response.status_code in {400, 409}:
                current = await client.get(
                    f"{self.base_url}/sessions/{self.settings.openwa_session_id}",
                    headers=headers,
                )
                current.raise_for_status()
                return current.json()
            response.raise_for_status()
            return response.json()

    async def fetch_message_media(self, chat_id: str, message_id: str) -> MediaAttachment | None:
        if not self.settings.openwa_api_key:
            raise ValueError("OPENWA_API_KEY is required.")
        url = f"{self.base_url}/sessions/{self.settings.openwa_session_id}/messages"
        headers = {"X-API-Key": self.settings.openwa_api_key, "X-Request-ID": f"req_{uuid4().hex}"}
        params = {"chatId": chat_id, "limit": "100"}
        async with httpx.AsyncClient(timeout=20) as client:
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


def _media_attachment_from_message(message: dict[str, Any]) -> MediaAttachment | None:
    metadata_value = message.get("metadata")
    metadata: dict[str, Any] = metadata_value if isinstance(metadata_value, dict) else {}
    media = message.get("media") if isinstance(message.get("media"), dict) else None
    if media is None and isinstance(metadata.get("media"), dict):
        media = metadata["media"]
    if not isinstance(media, dict):
        return None
    return MediaAttachment(
        mimetype=str(media.get("mimetype") or media.get("mimeType") or "application/octet-stream"),
        filename=media.get("filename"),
        data_base64=media.get("data") or media.get("base64"),
        url=media.get("url"),
    )
