from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, UnidentifiedImageError

IMAGE_MAX_BYTES = 16 * 1024 * 1024
VIDEO_MAX_BYTES = 64 * 1024 * 1024
AUDIO_MAX_BYTES = 16 * 1024 * 1024
DOCUMENT_MAX_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class MediaMetadata:
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None


def inspect_media(data: bytes, mime_type: str) -> MediaMetadata:
    if mime_type.lower().startswith("image/"):
        return _inspect_image(data)
    return MediaMetadata()


def max_media_bytes(mime_type: str) -> int:
    normalized = mime_type.lower()
    if normalized.startswith("image/"):
        return IMAGE_MAX_BYTES
    if normalized.startswith("video/"):
        return VIDEO_MAX_BYTES
    if normalized.startswith("audio/"):
        return AUDIO_MAX_BYTES
    return DOCUMENT_MAX_BYTES if normalized.startswith("application/") else DEFAULT_MAX_BYTES


def validate_media_size(data: bytes, mime_type: str) -> None:
    limit = max_media_bytes(mime_type)
    if len(data) > limit:
        raise ValueError(f"Media payload exceeds limit for {mime_type}: {len(data)} bytes > {limit} bytes")


def _inspect_image(data: bytes) -> MediaMetadata:
    try:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
    except (OSError, UnidentifiedImageError):
        return MediaMetadata()
    return MediaMetadata(width=width, height=height)
