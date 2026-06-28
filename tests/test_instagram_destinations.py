from media_automata.agents.graph import (
    attach_intent_media_assets,
    dedupe_instagram_destinations,
    expand_instagram_destinations,
    instagram_story_sources,
)
from media_automata.instagram_story_actions import (
    INSTAGRAM_STORY_EDITOR_ACTIONS_KEY,
    instagram_story_actions_from_raw_command,
)
from media_automata.platforms.instagram_native import InstagramNativeWorker
from media_automata.schemas import CommandIntent, Platform, PlatformContent


def test_expands_explicit_instagram_feed_and_story() -> None:
    content = PlatformContent(platform=Platform.INSTAGRAM, caption="caption", media_asset_ids=["asset_1"])
    intent = CommandIntent(intent="publish", platforms=[Platform.INSTAGRAM])

    expanded = expand_instagram_destinations(
        [content],
        intent=intent,
        raw_command="/post to Instagram feed and also Instagram Story",
    )

    assert [item.mode for item in expanded] == ["feed", "story"]
    assert [item.media_asset_ids for item in expanded] == [["asset_1"], ["asset_1"]]
    assert [item.extra for item in expanded] == [
        {"instagram_destination": "feed"},
        {"instagram_destination": "story", "instagram_story_source": "media"},
    ]


def test_attaches_intent_media_assets_when_llm_omits_them() -> None:
    content = PlatformContent(platform=Platform.INSTAGRAM, caption="caption")

    updated = attach_intent_media_assets(content, ["asset_1"])

    assert updated.media_asset_ids == ["asset_1"]


def test_story_only_instagram_request_does_not_create_feed_task() -> None:
    content = PlatformContent(platform=Platform.INSTAGRAM, caption="caption")
    intent = CommandIntent(intent="publish", platforms=[Platform.INSTAGRAM])

    expanded = expand_instagram_destinations(
        [content],
        intent=intent,
        raw_command="/post this to Instagram Story",
    )

    assert [item.mode for item in expanded] == ["story"]


def test_dedupes_repeated_instagram_feed_and_story_tasks() -> None:
    contents = [
        PlatformContent(platform=Platform.INSTAGRAM, caption="first", mode="feed"),
        PlatformContent(platform=Platform.INSTAGRAM, caption="first", mode="story"),
        PlatformContent(platform=Platform.INSTAGRAM, caption="second", mode="feed"),
        PlatformContent(platform=Platform.INSTAGRAM, caption="second", mode="story"),
        PlatformContent(platform=Platform.X, text="x copy"),
    ]

    deduped = dedupe_instagram_destinations(contents)

    assert [(item.platform, item.mode, item.primary_text) for item in deduped] == [
        (Platform.INSTAGRAM, "feed", "first"),
        (Platform.INSTAGRAM, "story", "first"),
        (Platform.X, "single", "x copy"),
    ]


def test_share_feed_post_to_story_gets_distinct_story_source() -> None:
    content = PlatformContent(platform=Platform.INSTAGRAM, caption="caption")
    intent = CommandIntent(intent="publish", platforms=[Platform.INSTAGRAM])

    expanded = expand_instagram_destinations(
        [content],
        intent=intent,
        raw_command="/post this to Instagram feed and add the Instagram post to Story after it is posted",
    )

    assert [(item.mode, item.extra) for item in expanded] == [
        ("feed", {"instagram_destination": "feed"}),
        ("story", {"instagram_destination": "story", "instagram_story_source": "feed_post"}),
    ]


def test_can_request_direct_story_and_feed_post_share_story_separately() -> None:
    content = PlatformContent(platform=Platform.INSTAGRAM, caption="caption")
    intent = CommandIntent(intent="publish", platforms=[Platform.INSTAGRAM])

    expanded = expand_instagram_destinations(
        [content],
        intent=intent,
        raw_command=(
            "/post this to Instagram feed, direct story, and also share the Instagram post to Story after it is posted"
        ),
    )
    deduped = dedupe_instagram_destinations(expanded)

    assert [(item.mode, item.extra.get("instagram_story_source")) for item in deduped] == [
        ("feed", None),
        ("story", "media"),
        ("story", "feed_post"),
    ]


def test_instagram_story_source_detection() -> None:
    assert instagram_story_sources("/post this photo directly to story") == ["media"]
    assert instagram_story_sources("/post this to all 3 platforms /direct story") == ["media"]
    assert instagram_story_sources("/post this and add the insta post to story after it has been posted") == [
        "feed_post"
    ]
    assert instagram_story_sources("/post instagram latest post to story") == ["feed_post"]
    assert instagram_story_sources("/post this to all 3 platforms /feed to story as well") == ["feed_post"]
    assert instagram_story_sources("/post this to all 3 platforms /feed-to-story as well") == ["feed_post"]


def test_existing_latest_feed_post_to_story_is_story_only() -> None:
    content = PlatformContent(platform=Platform.INSTAGRAM, caption="caption")
    intent = CommandIntent(intent="publish", platforms=[Platform.INSTAGRAM], instagram_targets=["feed", "story"])

    expanded = expand_instagram_destinations(
        [content],
        intent=intent,
        raw_command="/post instagram /feed-to-story latest post to story\nstory text: backend native route smoke",
    )

    assert [(item.mode, item.extra) for item in expanded] == [
        (
            "story",
            {
                "instagram_destination": "story",
                "instagram_story_source": "feed_post",
                "instagram_story_editor_actions": [
                    {"type": "text", "text": "backend native route smoke", "position": "center"}
                ],
                "instagram_story_requires_native_editor": True,
            },
        )
    ]


def test_feed_to_story_keyword_creates_feed_and_feed_post_story() -> None:
    content = PlatformContent(platform=Platform.INSTAGRAM, caption="caption")
    intent = CommandIntent(intent="publish", platforms=[Platform.INSTAGRAM])

    expanded = expand_instagram_destinations(
        [content],
        intent=intent,
        raw_command="/post this to all 3 platforms /feed to story as well",
    )

    assert [(item.mode, item.extra) for item in expanded] == [
        ("feed", {"instagram_destination": "feed"}),
        ("story", {"instagram_destination": "story", "instagram_story_source": "feed_post"}),
    ]


def test_feed_to_story_story_editor_actions_are_semantic() -> None:
    content = PlatformContent(platform=Platform.INSTAGRAM, caption="caption")
    intent = CommandIntent(intent="publish", platforms=[Platform.INSTAGRAM])

    expanded = expand_instagram_destinations(
        [content],
        intent=intent,
        raw_command="""\
/post this to Instagram feed and /feed-to-story
story text: New post is live
story link: post
story music: Glory
story layout: card large center
""",
    )

    story = expanded[1]
    assert story.extra["instagram_story_source"] == "feed_post"
    assert story.extra["instagram_story_requires_native_editor"] is True
    assert story.extra[INSTAGRAM_STORY_EDITOR_ACTIONS_KEY] == [
        {"type": "text", "text": "New post is live", "position": "center"},
        {"type": "link", "url": "auto_feed_post_url", "label": ""},
        {"type": "music", "query": "Glory", "section": "best_match"},
        {"type": "resize", "target": "post_card", "scale": "large"},
        {"type": "move", "target": "post_card", "position": "center"},
    ]


def test_story_music_can_use_first_suggested_song() -> None:
    actions = instagram_story_actions_from_raw_command(
        "/post this to instagram story\nstory music: suggested",
        source="media",
    )

    assert {"type": "music", "query": "suggested", "section": "suggested"} in actions


def test_bare_add_music_defaults_to_suggested() -> None:
    command = """/post to all 3 platforms 21 53 jun 26
Instagram caption - gg
post to story
story text: New post
center the story text
add music"""
    actions = instagram_story_actions_from_raw_command(command, source="media")

    assert {"type": "music", "query": "suggested", "section": "suggested"} in actions


def test_add_music_to_story_defaults_to_suggested() -> None:
    command = """/post to instagram at june 26 22:38
caption - hello test
/feed to story
story text: New post
left align the story text
add music to story"""
    actions = instagram_story_actions_from_raw_command(command, source="feed_post")

    assert {"type": "music", "query": "suggested", "section": "suggested"} in actions


def test_native_story_actions_run_layout_before_stickers_and_text() -> None:
    actions = [
        {"type": "text", "text": "after"},
        {"type": "mention", "username": "account"},
        {"type": "music", "query": "suggested"},
        {"type": "move", "target": "post_card", "position": "top"},
        {"type": "link", "url": "https://example.com"},
        {"type": "tap_card_variant", "target": "post_card"},
        {"type": "resize", "target": "post_card", "scale": "large"},
    ]

    ordered = InstagramNativeWorker._ordered_story_editor_actions(actions)

    assert [action["type"] for action in ordered] == [
        "resize",
        "move",
        "tap_card_variant",
        "music",
        "link",
        "text",
    ]
    assert ordered[-1]["text"] == "after\n@account"
