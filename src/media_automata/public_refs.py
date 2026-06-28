from __future__ import annotations

import re

PUBLIC_REF_HEX_LEN = 8
PUBLIC_REF_RE = re.compile(r"^#?(?P<hex>[a-f0-9]{6,12})$", re.IGNORECASE)


def format_public_ref(entity_id: str) -> str:
    """Return a short, easy-to-type public reference such as #a788aa85."""
    if "_" in entity_id:
        _, suffix = entity_id.split("_", 1)
    else:
        suffix = entity_id
    return f"#{suffix[:PUBLIC_REF_HEX_LEN].lower()}"


def normalize_prefixed_ref(ref: str, prefix: str) -> str:
    cleaned = ref.strip().lstrip("#").lower()
    if cleaned.startswith(f"{prefix}_"):
        return cleaned
    match = PUBLIC_REF_RE.fullmatch(cleaned)
    hex_part = match.group("hex") if match else cleaned
    return f"{prefix}_{hex_part}"


def extract_public_ref(text: str, *, prefix: str) -> str | None:
    hash_match = re.search(r"#([a-f0-9]{6,12})\b", text, flags=re.IGNORECASE)
    if hash_match:
        return hash_match.group(1).lower()
    prefixed_match = re.search(rf"\b{prefix}_([a-f0-9]+)\b", text, flags=re.IGNORECASE)
    if prefixed_match:
        return prefixed_match.group(1).lower()
    tokens = text.strip().split()
    if len(tokens) >= 2 and tokens[0].lower() in {"/status", "/retry"}:
        candidate = tokens[1].strip().lstrip("#").lower()
        if candidate:
            return candidate
    if len(tokens) >= 3 and tokens[0].lower() == "/todo" and tokens[1].lower() in {"done", "check"}:
        candidate = tokens[2].strip().lstrip("#").lower()
        if candidate:
            return candidate
    return None
