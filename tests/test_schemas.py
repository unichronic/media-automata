from media_automata.schemas import (
    CommandIntent,
    IncomingWhatsAppMessage,
    JobMode,
    Platform,
    PlatformContent,
    PlatformTaskPayload,
)


def test_command_intent_defaults_to_main_account_and_normalizes_platforms() -> None:
    intent = CommandIntent.model_validate({"intent": "publish", "platforms": "linkedin, x"})

    assert intent.account == "main_brand"
    assert intent.platforms == [Platform.LINKEDIN, Platform.X]


def test_incoming_whatsapp_message_allows_text_only_command() -> None:
    message = IncomingWhatsAppMessage(
        message_id="msg_1",
        from_number="+10000000000",
        chat_id="+10000000000@c.us",
        body="/accounts",
    )

    assert message.media is None
    assert message.from_me is False


def test_platform_task_payload_validates_nested_content() -> None:
    payload = PlatformTaskPayload(
        job_id="job_1",
        platform=Platform.INSTAGRAM,
        account="main_brand",
        mode=JobMode.PUBLISH,
        content=PlatformContent(platform=Platform.INSTAGRAM, caption="caption"),
    )

    assert payload.content.primary_text == "caption"
