from typing import cast

from media_automata.agents.graph import expand_instagram_destinations, instagram_story_sources
from media_automata.platforms.instagram import VIDEO_EXTENSIONS
from media_automata.platforms.instagram_native import InstagramNativeWorker
from media_automata.repository import Repository
from media_automata.schemas import CommandIntent, JobMode, Platform, PlatformContent, PlatformTaskPayload
from media_automata.worker import BrowserTaskRunner


def test_video_extensions_include_common_whatsapp_formats() -> None:
    assert ".mp4" in VIDEO_EXTENSIONS
    assert ".mov" in VIDEO_EXTENSIONS


def test_reel_to_story_creates_reel_and_story_tasks() -> None:
    content = PlatformContent(platform=Platform.INSTAGRAM, caption="launch reel", media_asset_ids=["asset_1"])
    intent = CommandIntent(intent="publish", platforms=[Platform.INSTAGRAM])

    expanded = expand_instagram_destinations(
        [content],
        intent=intent,
        raw_command="/post this as instagram reel and /reel to story",
    )

    assert [(item.mode, item.extra.get("instagram_story_source")) for item in expanded] == [
        ("reel", None),
        ("story", "feed_post"),
    ]


def test_reel_story_source_detection() -> None:
    assert instagram_story_sources("/post instagram reel and /reel-to-story") == ["feed_post"]
    assert instagram_story_sources("/post share the reel to story after posting") == ["feed_post"]


def test_shared_story_text_actions_remain_editor_overlays() -> None:
    caption, remaining = InstagramNativeWorker._split_shared_story_caption_actions(
        [
            {"type": "text", "text": "New reel is live"},
            {"type": "mention", "username": "verses_a_n_d_volumes"},
            {"type": "music", "query": "suggested"},
            {"type": "link", "url": "https://example.com"},
        ]
    )

    assert caption == "New reel is live\n@verses_a_n_d_volumes"
    assert remaining == [
        {"type": "music", "query": "suggested"},
        {"type": "link", "url": "https://example.com"},
    ]


def test_feed_post_story_text_stays_in_editor_actions() -> None:
    from media_automata.instagram_story_actions import instagram_story_actions_from_raw_command

    actions = instagram_story_actions_from_raw_command(
        """/post to instagram at june 26 23:05
insta caption - hello test
/feed to story
story text: New post
left align the story text
add music to story""",
        source="feed_post",
    )

    assert {"type": "text", "text": "New post", "position": "left"} in actions
    assert {"type": "music", "query": "suggested", "section": "suggested"} in actions


def test_worker_hydrates_story_from_completed_reel() -> None:
    from types import SimpleNamespace

    story_payload = PlatformTaskPayload(
        job_id="job_1",
        platform=Platform.INSTAGRAM,
        account="main_brand",
        mode=JobMode.PUBLISH,
        content=PlatformContent(
            platform=Platform.INSTAGRAM,
            mode="story",
            extra={"instagram_story_source": "feed_post"},
        ),
    )
    reel_task = SimpleNamespace(
        task_payload={
            "job_id": "job_1",
            "platform": "instagram",
            "account": "main_brand",
            "mode": "publish",
            "content": {
                "platform": "instagram",
                "mode": "reel",
                "caption": "launch",
                "text": "",
                "hashtags": [],
                "media_asset_ids": [],
                "posts": [],
                "extra": {},
            },
        },
        result={"status": "success", "result_url": "https://www.instagram.com/reel/abc123/"},
    )

    class FakeScalars:
        def __init__(self, items):
            self._items = items

        def __iter__(self):
            return iter(self._items)

    class FakeSession:
        def scalars(self, _stmt):
            return FakeScalars([reel_task])

    class FakeRepo:
        session = FakeSession()

    hydrated = BrowserTaskRunner._hydrate_payload_from_job_results(cast(Repository, FakeRepo()), story_payload)

    assert hydrated.content.extra["instagram_post_url"] == "https://www.instagram.com/reel/abc123/"
