from __future__ import annotations

from typing import Any

from media_automata.ids import new_id
from media_automata.schemas import IncomingWhatsAppMessage, MediaAttachment


def _first(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def normalize_openwa_payload(payload: dict[str, Any]) -> IncomingWhatsAppMessage:
    """Normalize OpenWA-style webhooks and direct test payloads.

    OpenWA dispatches `{"event": "...", "data": {...}}`; direct tests may send
    the message object itself. This keeps the rest of the system independent of
    the gateway implementation.
    """
    raw_data = payload.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else payload
    raw_media = data.get("media")
    media_data: dict[str, Any] | None = raw_media if isinstance(raw_media, dict) else None
    raw_quoted = data.get("quotedMessage") or data.get("quoted_message") or {}
    quoted: dict[str, Any] = raw_quoted if isinstance(raw_quoted, dict) else {}

    media = _media_attachment(media_data)
    quoted_media = _media_attachment(quoted.get("media"))

    message_id = _first(data.get("id"), data.get("messageId"), data.get("message_id"), payload.get("id"))
    from_number = _first(data.get("from"), data.get("fromNumber"), data.get("sender"), data.get("chatId"), "unknown")
    chat_id = _first(data.get("chatId"), data.get("from"), from_number)

    return IncomingWhatsAppMessage(
        message_id=str(message_id or new_id("wamsg")),
        from_number=str(from_number),
        chat_id=str(chat_id),
        body=str(_first(data.get("body"), data.get("text"), data.get("message"), "")),
        timestamp=data.get("timestamp") or data.get("waTimestamp"),
        from_me=bool(data.get("fromMe", False)),
        is_group=bool(data.get("isGroup", str(chat_id).endswith("@g.us"))),
        media=media,
        quoted_message_id=quoted.get("id") if isinstance(quoted, dict) else None,
        quoted_body=quoted.get("body") if isinstance(quoted, dict) else None,
        quoted_media=quoted_media,
        raw=payload,
    )


def _media_attachment(value: Any) -> MediaAttachment | None:
    if not isinstance(value, dict):
        return None
    return MediaAttachment(
        mimetype=value.get("mimetype") or value.get("mimeType") or "application/octet-stream",
        filename=value.get("filename"),
        data_base64=value.get("data") or value.get("base64"),
        url=value.get("url"),
    )
