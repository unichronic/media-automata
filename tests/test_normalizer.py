from media_automata.whatsapp.normalizer import normalize_openwa_payload


def test_normalize_openwa_payload() -> None:
    message = normalize_openwa_payload(
        {
            "event": "message.received",
            "data": {
                "id": "abc",
                "from": "+911234567890",
                "chatId": "+911234567890@c.us",
                "body": "/social publish",
                "timestamp": 10,
                "media": {"mimetype": "image/png", "filename": "a.png", "data": "AA=="},
            },
        }
    )

    assert message.message_id == "abc"
    assert message.from_number == "+911234567890"
    assert message.chat_id == "+911234567890@c.us"
    assert message.media is not None
    assert message.media.mimetype == "image/png"


def test_normalize_self_sent_group_command_payload() -> None:
    message = normalize_openwa_payload(
        {
            "event": "message.received",
            "data": {
                "id": "self-group-1",
                "from": "919999999999@c.us",
                "to": "120363000000000000@g.us",
                "chatId": "120363000000000000@g.us",
                "body": "/post group trigger",
                "fromMe": True,
            },
        }
    )

    assert message.message_id == "self-group-1"
    assert message.from_number == "919999999999@c.us"
    assert message.chat_id == "120363000000000000@g.us"
    assert message.from_me is True
    assert message.is_group is True


def test_normalize_quoted_media_payload() -> None:
    message = normalize_openwa_payload(
        {
            "event": "message.received",
            "data": {
                "id": "cmd-1",
                "from": "+911234567890",
                "chatId": "+911234567890@c.us",
                "body": "/post this photo to instagram story",
                "quotedMessage": {
                    "id": "photo-1",
                    "body": "",
                    "media": {"mimetype": "image/jpeg", "filename": "older.jpg", "data": "AA=="},
                },
            },
        }
    )

    assert message.quoted_message_id == "photo-1"
    assert message.quoted_media is not None
    assert message.quoted_media.mimetype == "image/jpeg"
    assert message.quoted_media.filename == "older.jpg"
