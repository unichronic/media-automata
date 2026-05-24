from media_automata.platforms.browser_use_llm import _normalize_browser_use_output


def test_normalize_browser_use_duplicate_action_wrapper() -> None:
    parsed = {
        "thinking": "Need to type into the login field.",
        "action": [
            {"input": {"input": {"index": 852, "text": "<secret>login_identifier</secret>", "clear": True}}},
            {"click": {"click": {"index": 878}}},
        ],
    }

    normalized = _normalize_browser_use_output(parsed)

    assert normalized["action"] == [
        {"input": {"index": 852, "text": "<secret>login_identifier</secret>", "clear": True}},
        {"click": {"index": 878}},
    ]


def test_normalize_browser_use_keeps_valid_action_shape() -> None:
    parsed = {"action": [{"click": {"index": 4}}, {"done": {"text": "ok", "success": True}}]}

    assert _normalize_browser_use_output(parsed) == parsed
