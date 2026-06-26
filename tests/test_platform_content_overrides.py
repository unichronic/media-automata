from media_automata.agents.graph import (
    apply_platform_content_overrides,
    dedupe_platform_contents,
    extract_platform_content_overrides,
    extract_verbatim_post_text,
    normalize_intent_from_raw_command,
)
from media_automata.schemas import CommandIntent, JobMode, Platform, PlatformContent


def test_extract_platform_content_overrides_from_command_lines() -> None:
    raw_command = """\
/post schedule this for all 3 platforms at may 20 17:45
Instagram caption - gg
Twitter - short x copy
LinkedIn - hello
"""

    overrides = extract_platform_content_overrides(raw_command)

    assert overrides == {
        Platform.INSTAGRAM: "gg",
        Platform.X: "short x copy",
        Platform.LINKEDIN: "hello",
    }


def test_extract_platform_content_overrides_accepts_caption_without_separator() -> None:
    raw_command = """\
/post this at 1:55 may 21
Insta caption wall of glory
Twitter caption - GGs
LinkedIn caption lessgoo
Also add the insta post to insta story after its has been posted
"""

    overrides = extract_platform_content_overrides(raw_command)

    assert overrides == {
        Platform.INSTAGRAM: "wall of glory",
        Platform.X: "GGs",
        Platform.LINKEDIN: "lessgoo",
    }


def test_apply_platform_content_overrides_preserves_instagram_destination_modes() -> None:
    contents = [
        PlatformContent(platform=Platform.INSTAGRAM, caption="generated", mode="feed", hashtags=["tag"]),
        PlatformContent(platform=Platform.INSTAGRAM, caption="generated", mode="story", hashtags=["tag"]),
        PlatformContent(platform=Platform.X, text="generated", hashtags=["tag"]),
        PlatformContent(platform=Platform.LINKEDIN, text="generated", hashtags=["tag"]),
    ]

    updated = apply_platform_content_overrides(
        contents,
        "Instagram caption: gg\nTwitter - short x copy\nLinkedIn - hello",
    )

    assert updated[0].caption == "gg"
    assert updated[0].mode == "feed"
    assert updated[0].hashtags == []
    assert updated[1].caption == "gg"
    assert updated[1].mode == "story"
    assert updated[2].text == "short x copy"
    assert updated[2].hashtags == []
    assert updated[3].text == "hello"
    assert updated[3].hashtags == []


def test_plain_post_text_is_verbatim_for_requested_platforms() -> None:
    command = "/post hello shit you to linkedin and x"
    contents = [
        PlatformContent(platform=Platform.X, text="generated x", hashtags=["tag"]),
        PlatformContent(platform=Platform.LINKEDIN, text="generated linkedin", hashtags=["tag"]),
    ]

    assert extract_verbatim_post_text(command) == "hello shit you"

    updated = apply_platform_content_overrides(contents, command)

    assert updated[0].text == "hello shit you"
    assert updated[0].hashtags == []
    assert updated[1].text == "hello shit you"
    assert updated[1].hashtags == []


def test_explicit_generation_instruction_keeps_generated_content() -> None:
    command = "/post write a post on browser automation in 50 words to linkedin and x"
    contents = [
        PlatformContent(platform=Platform.X, text="generated x"),
        PlatformContent(platform=Platform.LINKEDIN, text="generated linkedin"),
    ]

    assert extract_verbatim_post_text(command) is None
    assert apply_platform_content_overrides(contents, command) == contents


def test_media_placeholder_clears_generated_caption_without_generation_instruction() -> None:
    contents = [
        PlatformContent(platform=Platform.INSTAGRAM, caption="generated caption", mode="feed"),
        PlatformContent(platform=Platform.X, text="generated x"),
    ]

    updated = apply_platform_content_overrides(contents, "/post this on all 3 platforms")

    assert updated[0].caption == ""
    assert updated[1].text == ""


def test_dedupe_platform_contents_removes_duplicate_single_destination_platforms() -> None:
    contents = [
        PlatformContent(platform=Platform.LINKEDIN, text="first linkedin"),
        PlatformContent(platform=Platform.LINKEDIN, text="duplicate linkedin"),
        PlatformContent(platform=Platform.X, text="first x"),
        PlatformContent(platform=Platform.X, text="duplicate x"),
        PlatformContent(platform=Platform.INSTAGRAM, caption="feed", mode="feed"),
        PlatformContent(
            platform=Platform.INSTAGRAM,
            caption="direct story",
            mode="story",
            extra={"instagram_story_source": "media"},
        ),
        PlatformContent(
            platform=Platform.INSTAGRAM,
            caption="feed post story",
            mode="story",
            extra={"instagram_story_source": "feed_post"},
        ),
    ]

    deduped = dedupe_platform_contents(contents)

    assert [(item.platform, item.primary_text, item.mode) for item in deduped] == [
        (Platform.LINKEDIN, "first linkedin", "single"),
        (Platform.X, "first x", "single"),
        (Platform.INSTAGRAM, "feed", "feed"),
        (Platform.INSTAGRAM, "direct story", "story"),
        (Platform.INSTAGRAM, "feed post story", "story"),
    ]


def test_normalize_intent_from_raw_command_keeps_all_platform_schedule_safe() -> None:
    intent = CommandIntent(intent="publish", mode=JobMode.PUBLISH, platforms=[])

    normalized = normalize_intent_from_raw_command(
        intent,
        "/post schedule this for all 3 platforms at may 20 17:45",
    )

    assert normalized.intent == "schedule"
    assert normalized.mode == JobMode.SCHEDULE
    assert normalized.platforms == [Platform.LINKEDIN, Platform.X, Platform.INSTAGRAM]
    assert normalized.scheduled_for == "/post schedule this for all 3 platforms at may 20 17:45"
