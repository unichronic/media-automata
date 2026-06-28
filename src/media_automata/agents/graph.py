from __future__ import annotations

import re
from datetime import datetime

from media_automata.agents.llm import LLMProvider
from media_automata.agents.prompts import COMMAND_PARSER_SYSTEM, CONTENT_SYSTEM
from media_automata.instagram_story_actions import (
    INSTAGRAM_STORY_EDITOR_ACTIONS_KEY,
    INSTAGRAM_STORY_REQUIRES_NATIVE_KEY,
    instagram_story_actions_from_raw_command,
    story_actions_require_native,
)
from media_automata.schemas import (
    AgentPlan,
    CommandIntent,
    ContentStrategy,
    JobMode,
    Platform,
    PlatformContent,
    PlatformContentPlan,
)

X_POST_LIMIT = 280
PLATFORM_CONTENT_LINE_RE = re.compile(
    r"^\s*(?P<label>instagram|insta|ig|twitter|x|linkedin)"
    r"(?:(?:\s+(?:caption|post|text))?\s*[-:]\s*|\s+(?:caption|post|text)\s+)"
    r"(?P<text>.+?)\s*$",
    re.IGNORECASE,
)
GENERIC_CAPTION_LINE_RE = re.compile(
    r"^\s*(?P<label>caption|text|post)\s*[-:]\s*(?P<text>.+?)\s*$",
    re.IGNORECASE,
)
ROUTE_AND_SCHEDULE_BODY_RE = re.compile(
    r"^(?:to|on|for)\s+(?:(?:linkedin|linked\s*in|twitter|x|insta|instagram|ig)"
    r"(?:\s*(?:,|and|&|\+)\s*)?)+\s*"
    r"(?:at|for|on|from)?\s*(?:\d|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|today|tomorrow|schedule).*$",
    re.IGNORECASE,
)
ALL_PLATFORMS_RE = re.compile(r"\ball\s+(?:3|three|platforms?|socials?)\b", re.IGNORECASE)
SCHEDULE_HINT_RE = re.compile(r"\bschedule\b", re.IGNORECASE)
CONTENT_GENERATION_RE = re.compile(
    r"\b(?:generate|write|draft|create|compose|make)\b.*\b(?:caption|post|copy|text|thread|words?)\b"
    r"|\b(?:caption|post|copy|text|thread)\b.*\b(?:generate|write|draft|create|compose|make)\b",
    re.IGNORECASE | re.DOTALL,
)
PLATFORM_DESTINATION_SUFFIX_RE = re.compile(
    r"\s+\b(?:to|on|for)\s+(?:(?:linkedin|linked\s*in|twitter|x|insta|instagram|ig)"
    r"(?:\s*(?:,|and|&|\+)\s*)?)+\s*$",
    re.IGNORECASE,
)
NON_CONTENT_PLACEHOLDERS = {
    "this",
    "this photo",
    "this image",
    "this pic",
    "this picture",
    "this media",
    "this video",
    "this on all 3 platforms",
    "this on all three platforms",
    "this to all 3 platforms",
    "this to all three platforms",
    "this for all 3 platforms",
    "this for all three platforms",
}
FEED_TO_STORY_KEYWORD_RE = re.compile(
    r"(?<!\w)/?feed(?:\s+to\s+|\s*[-_]\s*to\s*[-_]\s*|\s*[-_]\s*)story\b",
    re.IGNORECASE,
)
DIRECT_STORY_KEYWORD_RE = re.compile(
    r"(?<!\w)/?(?:direct\s*(?:[-_]\s*)?story|story\s*(?:[-_]\s*)?direct|media\s*(?:[-_]\s*)?story)\b",
    re.IGNORECASE,
)
INSTAGRAM_STORY_SHARE_RE = re.compile(
    r"\b(?:share|add|put)\b.*\b(?:insta|instagram|feed)?\s*(?:post|reel)\b.*\b(?:insta|instagram)?\s*stor(?:y|ies)\b"
    r"|\bstor(?:y|ies)\b.*\bafter\b.*\b(?:post|reel)(?:ed|ing)?\b",
    re.IGNORECASE,
)
REEL_TO_STORY_KEYWORD_RE = re.compile(
    r"(?<!\w)/?reel(?:\s+to\s+|\s*[-_]\s*to\s*[-_]\s*|\s*[-_]\s*)story\b",
    re.IGNORECASE,
)
INSTAGRAM_EXISTING_FEED_POST_STORY_RE = re.compile(
    r"\b(?:latest|last|recent|previous|existing|current|own)\b.{0,80}\b(?:insta|instagram|feed)?\s*post\b"
    r"|\b(?:insta|instagram|feed)?\s*post\b.{0,80}\b(?:latest|last|recent|previous|existing|current|own)\b"
    r"|\balready\s+(?:posted|published)\b"
    r"|https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/",
    re.IGNORECASE | re.DOTALL,
)
INSTAGRAM_FEED_DESTINATION_RE = re.compile(
    r"\b(?:insta|instagram|ig)\s+(?:feed|grid)\b"
    r"|\b(?:to|on)\s+(?:the\s+)?(?:(?:insta|instagram|ig)\s+)?(?:feed|grid)\b"
    r"|\b(?:feed|grid)\s+(?:post|caption)\s*[-:]",
    re.IGNORECASE,
)
INSTAGRAM_DIRECT_STORY_RE = re.compile(
    r"\b(?:direct|directly)\b.*\bstor(?:y|ies)\b"
    r"|\bstor(?:y|ies)\s+only\b"
    r"|\b(?:post|upload|share)\b.*\b(?:photo|image|pic|picture|media|video)\b.*\bstor(?:y|ies)\b",
    re.IGNORECASE,
)
INSTAGRAM_GENERIC_THIS_STORY_RE = re.compile(
    r"\b(?:post|upload|share)\b.*\bthis\b.*\bstor(?:y|ies)\b",
    re.IGNORECASE,
)


class SocialAgentGraph:
    """Explicit agent graph for command parsing, content strategy, and platform content.

    This class keeps the graph simple and inspectable while matching the LangGraph
    node boundaries described in the design.
    """

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    async def run(self, raw_command: str, *, media_asset_ids: list[str] | None = None) -> AgentPlan:
        intent = await self.parse_command(raw_command)
        intent.media_asset_ids = media_asset_ids or []
        strategy = await self.create_strategy(intent)
        platform_contents = await self.create_platform_content(intent, strategy, raw_command=raw_command)
        return AgentPlan(intent=intent, strategy=strategy, platform_contents=platform_contents)

    async def parse_command(self, raw_command: str) -> CommandIntent:
        now = datetime.now().astimezone().isoformat()
        intent = await self.llm.generate_structured(
            system=COMMAND_PARSER_SYSTEM,
            user=f"Current local datetime: {now}\n\nCommand:\n{raw_command}",
            model_type=CommandIntent,
        )
        return normalize_intent_from_raw_command(intent, raw_command)

    async def create_strategy(self, intent: CommandIntent) -> ContentStrategy:
        return await self.llm.generate_structured(
            system="Create a compact content strategy for this social publishing job. Return JSON.",
            user=intent.model_dump_json(),
            model_type=ContentStrategy,
        )

    async def create_platform_content(
        self,
        intent: CommandIntent,
        strategy: ContentStrategy,
        *,
        raw_command: str = "",
    ) -> list[PlatformContent]:
        plan = await self.llm.generate_structured(
            system=CONTENT_SYSTEM,
            user=(
                "Create platform-specific publishing content for this job.\n\n"
                f"Intent:\n{intent.model_dump_json()}\n\n"
                f"Strategy:\n{strategy.model_dump_json()}\n\n"
                "Return an object with a `contents` array. Include one item for each requested platform destination. "
                "If Instagram feed and Instagram Story are both requested, include separate Instagram feed and story "
                "items."
            ),
            model_type=PlatformContentPlan,
        )
        contents = [
            normalize_platform_content(attach_intent_media_assets(content, intent.media_asset_ids))
            for content in plan.contents
        ]
        expanded = expand_instagram_destinations(contents, intent=intent, raw_command=raw_command)
        overridden = apply_platform_content_overrides(expanded, raw_command)
        return dedupe_platform_contents(overridden)


def normalize_platform_content(content: PlatformContent) -> PlatformContent:
    if content.platform == Platform.X:
        return normalize_x_content(content)
    return content


def attach_intent_media_assets(content: PlatformContent, media_asset_ids: list[str]) -> PlatformContent:
    if content.media_asset_ids or not media_asset_ids:
        return content
    return content.model_copy(update={"media_asset_ids": media_asset_ids})


def normalize_intent_from_raw_command(intent: CommandIntent, raw_command: str) -> CommandIntent:
    updates: dict[str, object] = {}
    if intent.intent in {"publish", "draft", "schedule", "unknown"}:
        if ALL_PLATFORMS_RE.search(raw_command) or not intent.platforms:
            updates["platforms"] = [Platform.LINKEDIN, Platform.X, Platform.INSTAGRAM]
        if SCHEDULE_HINT_RE.search(raw_command):
            updates["intent"] = "schedule"
            updates["mode"] = JobMode.SCHEDULE
            if not intent.scheduled_for:
                updates["scheduled_for"] = raw_command
    if not updates:
        return intent
    return intent.model_copy(update=updates)


def expand_instagram_destinations(
    contents: list[PlatformContent],
    *,
    intent: CommandIntent,
    raw_command: str,
) -> list[PlatformContent]:
    expanded: list[PlatformContent] = []
    for content in contents:
        if content.platform != Platform.INSTAGRAM:
            expanded.append(content)
            continue
        modes = instagram_destination_modes(raw_command, intent, content)
        for mode in modes:
            if mode == "story":
                for source in instagram_story_sources(raw_command):
                    actions = instagram_story_actions_from_raw_command(raw_command, source=source)
                    extra = {**content.extra, "instagram_destination": mode, "instagram_story_source": source}
                    if actions:
                        extra[INSTAGRAM_STORY_EDITOR_ACTIONS_KEY] = actions
                    if story_actions_require_native(actions):
                        extra[INSTAGRAM_STORY_REQUIRES_NATIVE_KEY] = True
                    expanded.append(content.model_copy(update={"mode": mode, "extra": extra}))
                continue
            extra = {**content.extra, "instagram_destination": mode}
            expanded.append(content.model_copy(update={"mode": mode, "extra": extra}))
    return expanded


def dedupe_instagram_destinations(contents: list[PlatformContent]) -> list[PlatformContent]:
    return dedupe_platform_contents(contents)


def dedupe_platform_contents(contents: list[PlatformContent]) -> list[PlatformContent]:
    deduped: list[PlatformContent] = []
    seen_instagram_modes: set[str] = set()
    seen_single_platforms: set[Platform] = set()
    for content in contents:
        if content.platform != Platform.INSTAGRAM:
            if content.platform in seen_single_platforms:
                continue
            seen_single_platforms.add(content.platform)
            deduped.append(content)
            continue
        mode = (
            content.mode
            if content.mode in {"feed", "story", "reel"}
            else content.extra.get("instagram_destination", "feed")
        )
        key = mode
        if mode == "story":
            key = f"story:{content.extra.get('instagram_story_source', 'media')}"
        if key in seen_instagram_modes:
            continue
        seen_instagram_modes.add(str(key))
        deduped.append(content)
    return deduped


def instagram_destination_modes(
    raw_command: str,
    intent: CommandIntent,
    content: PlatformContent,
) -> list[str]:
    requested = set(intent.instagram_targets)
    lower = raw_command.lower()
    explicit_story = bool(re.search(r"\b(story|stories)\b", lower))
    raw_without_feed_to_story = FEED_TO_STORY_KEYWORD_RE.sub(" ", raw_command)
    explicit_feed = bool(INSTAGRAM_FEED_DESTINATION_RE.search(raw_without_feed_to_story))
    explicit_reel = bool(re.search(r"\b(reel|reels)\b", lower))
    explicit_reel_to_story = bool(REEL_TO_STORY_KEYWORD_RE.search(raw_command))
    explicit_story_share = (
        bool(FEED_TO_STORY_KEYWORD_RE.search(raw_command))
        or bool(REEL_TO_STORY_KEYWORD_RE.search(raw_command))
        or bool(INSTAGRAM_STORY_SHARE_RE.search(raw_command))
        or instagram_feed_post_story_uses_existing_post(raw_command)
    )
    uses_existing_feed_post = explicit_story_share and instagram_feed_post_story_uses_existing_post(raw_command)

    if uses_existing_feed_post and not explicit_feed:
        requested.discard("feed")
        requested.discard("grid")

    if explicit_story_share:
        requested.add("story")
        if not uses_existing_feed_post:
            if explicit_reel or explicit_reel_to_story:
                requested.add("reel")
            else:
                requested.add("feed")
    if explicit_feed:
        requested.add("feed")
    if explicit_story:
        requested.add("story")
    if explicit_reel:
        requested.add("reel")

    if requested:
        ordered = [mode for mode in ("feed", "reel", "story") if mode in requested]
        return ordered or ["feed"]
    if content.mode in {"feed", "story", "reel"}:
        return [content.mode]
    return ["feed"]


def instagram_feed_post_story_uses_existing_post(raw_command: str) -> bool:
    return bool(re.search(r"\bstor(?:y|ies)\b", raw_command, re.IGNORECASE)) and bool(
        INSTAGRAM_EXISTING_FEED_POST_STORY_RE.search(raw_command)
    )


def instagram_story_sources(raw_command: str) -> list[str]:
    share_published_post = (
        bool(FEED_TO_STORY_KEYWORD_RE.search(raw_command))
        or bool(REEL_TO_STORY_KEYWORD_RE.search(raw_command))
        or bool(INSTAGRAM_STORY_SHARE_RE.search(raw_command))
        or instagram_feed_post_story_uses_existing_post(raw_command)
    )
    direct_media = bool(DIRECT_STORY_KEYWORD_RE.search(raw_command)) or bool(
        INSTAGRAM_DIRECT_STORY_RE.search(raw_command)
    ) or (
        not share_published_post and bool(INSTAGRAM_GENERIC_THIS_STORY_RE.search(raw_command))
    )
    sources: list[str] = []
    if direct_media:
        sources.append("media")
    if share_published_post:
        sources.append("feed_post")
    return sources or ["media"]


def extract_platform_content_overrides(raw_command: str) -> dict[Platform, str]:
    overrides: dict[Platform, str] = {}
    for line in raw_command.splitlines():
        match = PLATFORM_CONTENT_LINE_RE.match(line)
        if not match:
            continue
        label = match.group("label").lower()
        text = match.group("text").strip()
        if not text:
            continue
        if label in {"instagram", "insta", "ig"}:
            overrides[Platform.INSTAGRAM] = text
        elif label in {"twitter", "x"}:
            overrides[Platform.X] = text
        elif label == "linkedin":
            overrides[Platform.LINKEDIN] = text
    return overrides


def extract_generic_caption(raw_command: str) -> str | None:
    for line in raw_command.splitlines():
        match = GENERIC_CAPTION_LINE_RE.match(line)
        if not match:
            continue
        text = match.group("text").strip()
        if text:
            return text
    return None


def single_platform_from_contents(contents: list[PlatformContent]) -> Platform | None:
    platforms = {content.platform for content in contents}
    if len(platforms) != 1:
        return None
    return next(iter(platforms))


def extract_verbatim_post_text(raw_command: str) -> str | None:
    first_line = raw_command.strip().splitlines()[0] if raw_command.strip() else ""
    match = re.match(r"^\s*/post\b(?P<body>.*)$", first_line, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    body = match.group("body").strip()
    if not body or CONTENT_GENERATION_RE.search(body):
        return None
    body = re.sub(r"^this\s+text\s+", "", body, flags=re.IGNORECASE).strip()
    body = PLATFORM_DESTINATION_SUFFIX_RE.sub("", body).strip()
    body = body.strip("\"' ")
    if not body or body.lower() in NON_CONTENT_PLACEHOLDERS or ROUTE_AND_SCHEDULE_BODY_RE.match(body):
        return ""
    return body


def apply_platform_content_overrides(
    contents: list[PlatformContent],
    raw_command: str,
) -> list[PlatformContent]:
    overrides = extract_platform_content_overrides(raw_command)
    generic_caption = extract_generic_caption(raw_command)
    if generic_caption and not overrides:
        single_platform = single_platform_from_contents(contents)
        if single_platform is not None:
            overrides = {single_platform: generic_caption}
    verbatim_text = extract_verbatim_post_text(raw_command)
    if not overrides and verbatim_text is None:
        return contents

    updated: list[PlatformContent] = []
    for content in contents:
        override = overrides.get(content.platform)
        if override is None and verbatim_text is not None:
            override = verbatim_text
        if not override:
            if override == "":
                if content.platform == Platform.INSTAGRAM:
                    content = content.model_copy(update={"caption": "", "text": "", "posts": [], "hashtags": []})
                else:
                    content = content.model_copy(update={"text": "", "caption": "", "posts": [], "hashtags": []})
                updated.append(normalize_platform_content(content))
                continue
            updated.append(content)
            continue

        if content.platform == Platform.INSTAGRAM:
            content = content.model_copy(update={"caption": override, "text": "", "posts": [], "hashtags": []})
        else:
            content = content.model_copy(update={"text": override, "caption": "", "posts": [], "hashtags": []})
        updated.append(normalize_platform_content(content))
    return updated


def normalize_x_content(content: PlatformContent) -> PlatformContent:
    source_posts = content.posts or [content.caption or content.text]
    posts: list[str] = []
    for post in source_posts:
        posts.extend(split_x_post(post, limit=X_POST_LIMIT))
    if len(posts) <= 1:
        return content.model_copy(update={"posts": [], "text": posts[0] if posts else content.text, "mode": "single"})
    return content.model_copy(update={"posts": posts, "text": "", "caption": "", "mode": "thread"})


def split_x_post(text: str, *, limit: int = X_POST_LIMIT) -> list[str]:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return [clean] if clean else []

    posts: list[str] = []
    current = ""
    for word in clean.split(" "):
        if len(word) > limit:
            if current:
                posts.append(current)
                current = ""
            posts.extend(word[index : index + limit] for index in range(0, len(word), limit))
            continue
        candidate = f"{current} {word}".strip()
        if len(candidate) <= limit:
            current = candidate
        else:
            posts.append(current)
            current = word
    if current:
        posts.append(current)
    return posts
