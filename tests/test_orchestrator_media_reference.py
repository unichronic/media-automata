from media_automata.orchestrator import _content_requires_input_media, _expects_media_from_context
from media_automata.schemas import Platform, PlatformContent


def test_expects_media_for_reply_style_post_this_command() -> None:
    assert _expects_media_from_context("/post this on all 3 platforms")


def test_expects_media_for_explicit_photo_reference() -> None:
    assert _expects_media_from_context("/post this photo to instagram")


def test_does_not_require_media_for_plain_text_command() -> None:
    assert not _expects_media_from_context("/post LinkedIn - hello Twitter - hi")


def test_text_only_linkedin_and_x_do_not_require_input_media() -> None:
    assert not _content_requires_input_media(PlatformContent(platform=Platform.LINKEDIN, text="hello"))
    assert not _content_requires_input_media(PlatformContent(platform=Platform.X, text="hello"))


def test_instagram_feed_and_direct_story_require_input_media() -> None:
    assert _content_requires_input_media(PlatformContent(platform=Platform.INSTAGRAM, caption="hello", mode="feed"))
    assert _content_requires_input_media(
        PlatformContent(
            platform=Platform.INSTAGRAM,
            caption="hello",
            mode="story",
            extra={"instagram_story_source": "media"},
        )
    )


def test_instagram_feed_post_share_story_does_not_require_new_input_media() -> None:
    assert not _content_requires_input_media(
        PlatformContent(
            platform=Platform.INSTAGRAM,
            caption="hello",
            mode="story",
            extra={"instagram_story_source": "feed_post"},
        )
    )
