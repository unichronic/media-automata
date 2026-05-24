from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from media_automata.ids import new_id


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save_bytes(
        self,
        data: bytes,
        *,
        filename: str | None = None,
        prefix: str = "assets",
        mime_type: str | None = None,
    ) -> tuple[str, str]:
        digest = hashlib.sha256(data).hexdigest()
        ext = _extension_for(filename=filename, mime_type=mime_type)
        object_id = new_id(prefix.rstrip("s") or "asset")
        path = self.root / prefix / digest[:2] / f"{object_id}{ext}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"local://{path.relative_to(self.root).as_posix()}", digest

    def save_text(self, text: str, *, filename: str | None = None, prefix: str = "artifacts") -> tuple[str, str]:
        data = text.encode("utf-8")
        return self.save_bytes(data, filename=filename or "artifact.txt", prefix=prefix)

    def resolve(self, storage_uri: str) -> Path:
        if not storage_uri.startswith("local://"):
            raise ValueError(f"Unsupported storage URI: {storage_uri}")
        rel = storage_uri.removeprefix("local://")
        return self.root / rel


def _extension_for(*, filename: str | None, mime_type: str | None) -> str:
    if filename:
        ext = Path(filename).suffix
        if ext:
            return ext
    if mime_type:
        ext = mimetypes.guess_extension(mime_type.split(";")[0].strip().lower())
        if ext:
            return ".jpg" if ext == ".jpe" else ext
    return ".bin"
