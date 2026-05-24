from __future__ import annotations

import re
from typing import Any

INSTAGRAM_STORY_EDITOR_ACTIONS_KEY = "instagram_story_editor_actions"
INSTAGRAM_STORY_REQUIRES_NATIVE_KEY = "instagram_story_requires_native_editor"
AUTO_FEED_POST_URL = "auto_feed_post_url"

STORY_ACTION_LINE_RE = re.compile(
    r"^\s*(?:insta(?:gram)?\s+)?story\s+"
    r"(?P<label>text|caption|link|mention|music|font|color|layout|position|card)\s*[-:]\s*"
    r"(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
QUOTED_TEXT_RE = re.compile(r"\b(?:story\s+)?(?:text|caption)\s+[\"'“](?P<text>.+?)[\"'”]", re.IGNORECASE)
MENTION_RE = re.compile(r"(?:story\s+mention|mention)\s+@?(?P<username>[a-zA-Z0-9_.]+)", re.IGNORECASE)
MUSIC_RE = re.compile(r"(?:story\s+music|music|choose\s+music|add\s+music)\s*[-:]?\s*(?P<query>.+)", re.IGNORECASE)
SUGGESTED_MUSIC_RE = re.compile(
    r"\b(?:story\s+)?(?:music|song|audio)\b.*\b(?:suggested|recommended|first suggestion|first suggested)\b"
    r"|\b(?:suggested|recommended|first suggestion|first suggested)\b.*\b(?:music|song|audio)\b",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://[^\s,]+", re.IGNORECASE)


def instagram_story_actions_from_raw_command(raw_command: str, *, source: str) -> list[dict[str, Any]]:
    """Extract semantic Instagram Story editor actions from a WhatsApp command.

    These actions intentionally avoid coordinates. The native Android worker owns the actual gestures.
    """

    actions: list[dict[str, Any]] = []
    lower = raw_command.lower()

    line_values = _story_action_lines(raw_command)

    text_value = line_values.get("text") or line_values.get("caption") or _quoted_text(raw_command)
    if text_value:
        actions.append(
            {
                "type": "text",
                "text": text_value,
                "position": _position_from_text(text_value, raw_command) or "center",
                **_font_color_from_command(raw_command),
            }
        )

    link_value = line_values.get("link")
    if link_value or "add link to the post" in lower or "link to the post" in lower:
        url = _first_url(link_value or raw_command) or (AUTO_FEED_POST_URL if source == "feed_post" else "")
        if url:
            actions.append({"type": "link", "url": url, "label": _link_label(link_value or raw_command)})

    mention_value = line_values.get("mention")
    mention = _mention_username(mention_value or raw_command)
    if mention:
        actions.append(
            {
                "type": "mention",
                "username": mention,
                "position": _position_from_text(raw_command) or "center",
            }
        )

    music_value = line_values.get("music") or _music_query(raw_command) or _suggested_music_query(raw_command)
    if music_value:
        if _is_suggested_music_value(music_value):
            actions.append({"type": "music", "query": "suggested", "section": "suggested"})
        else:
            actions.append({"type": "music", "query": music_value, "section": "best_match"})

    layout_value = " ".join(
        value for key, value in line_values.items() if key in {"layout", "position", "card"}
    )
    layout_text = f"{raw_command} {layout_value}".lower()
    if source == "feed_post":
        actions.extend(_post_card_layout_actions(layout_text))
    else:
        actions.extend(_media_layout_actions(layout_text))

    return _dedupe_actions(actions)


def story_actions_require_native(actions: list[dict[str, Any]]) -> bool:
    return bool(actions)


def _story_action_lines(raw_command: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in raw_command.splitlines():
        match = STORY_ACTION_LINE_RE.match(line)
        if not match:
            continue
        label = match.group("label").lower()
        value = match.group("value").strip()
        if value:
            values[label] = value
    return values


def _quoted_text(raw_command: str) -> str | None:
    match = QUOTED_TEXT_RE.search(raw_command)
    if not match:
        return None
    return match.group("text").strip()


def _first_url(text: str) -> str | None:
    match = URL_RE.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,)")


def _link_label(text: str) -> str:
    match = re.search(r"\b(?:label|text)\s*[-:]\s*(?P<label>[^,]+)", text, re.IGNORECASE)
    if not match:
        return ""
    return match.group("label").strip()


def _mention_username(text: str) -> str | None:
    match = MENTION_RE.search(text)
    if not match:
        return None
    return match.group("username").strip().lstrip("@")


def _music_query(raw_command: str) -> str | None:
    for line in raw_command.splitlines():
        match = MUSIC_RE.search(line)
        if not match:
            continue
        query = match.group("query").strip(" -:")
        if query and not query.lower().startswith(("story", "to ", "on ")):
            return query
    return None


def _suggested_music_query(raw_command: str) -> str | None:
    return "suggested" if SUGGESTED_MUSIC_RE.search(raw_command) else None


def _is_suggested_music_value(value: str) -> bool:
    normalized = re.sub(r"[\s_-]+", " ", value.strip().lower())
    return normalized in {
        "suggested",
        "recommended",
        "first suggested",
        "first suggestion",
        "first recommended",
        "first recommendation",
        "instagram suggested",
        "instagram recommended",
    }


def _font_color_from_command(raw_command: str) -> dict[str, str]:
    values: dict[str, str] = {}
    font_match = re.search(r"\bstory\s+font\s*[-:]\s*(?P<font>[a-zA-Z0-9_ -]+)", raw_command, re.IGNORECASE)
    color_match = re.search(r"\bstory\s+color\s*[-:]\s*(?P<color>[a-zA-Z0-9_ -]+)", raw_command, re.IGNORECASE)
    if font_match:
        values["font"] = font_match.group("font").strip().lower()
    if color_match:
        values["color"] = color_match.group("color").strip().lower()
    return values


def _position_from_text(*values: str) -> str | None:
    text = " ".join(values).lower()
    positions = {
        "top left": ("top left", "upper left"),
        "top right": ("top right", "upper right"),
        "bottom left": ("bottom left", "lower left"),
        "bottom right": ("bottom right", "lower right"),
        "top": ("top", "above"),
        "bottom": ("bottom", "below"),
        "left": ("left",),
        "right": ("right",),
        "center": ("center", "middle", "centred", "centered"),
    }
    for position, markers in positions.items():
        if any(marker in text for marker in markers):
            return position
    return None


def _post_card_layout_actions(text: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if any(marker in text for marker in ("big", "bigger", "large", "larger", "zoom", "scale up")):
        actions.append({"type": "resize", "target": "post_card", "scale": "large"})
    elif any(marker in text for marker in ("small", "smaller", "scale down")):
        actions.append({"type": "resize", "target": "post_card", "scale": "small"})
    elif "full" in text:
        actions.append({"type": "resize", "target": "post_card", "scale": "full"})

    position = _position_from_text(text)
    if position:
        actions.append({"type": "move", "target": "post_card", "position": position})

    if any(marker in text for marker in ("tap card", "card style", "style variant", "change card")):
        actions.append({"type": "tap_card_variant", "target": "post_card"})
    return actions


def _media_layout_actions(text: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if "full" in text:
        actions.append({"type": "resize", "target": "media", "scale": "full"})
    elif "fit" in text:
        actions.append({"type": "resize", "target": "media", "scale": "fit"})
    position = _position_from_text(text)
    if position:
        actions.append({"type": "move", "target": "media", "position": position})
    return actions


def _dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for action in actions:
        key = (
            str(action.get("type")),
            str(action.get("target", "")),
            str(action.get("text") or action.get("url") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped
