from media_automata.platforms.instagram import classify_instagram_auth_state, classify_story_publish_state


def test_instagram_auth_prefers_authenticated_mobile_feed_over_generic_login_text() -> None:
    state = classify_instagram_auth_state(
        "Home Search Reels Your story Profile Forgot password",
        "https://www.instagram.com/",
        authenticated_control_visible=True,
    )

    assert state == "authenticated"


def test_instagram_auth_detects_login_screen_from_visible_inputs() -> None:
    state = classify_instagram_auth_state(
        "Log into Instagram",
        "https://www.instagram.com/accounts/login/",
        password_input_visible=True,
        login_input_visible=True,
    )

    assert state == "login"


def test_instagram_auth_detects_verification_before_login() -> None:
    state = classify_instagram_auth_state(
        "Enter the code we sent to your email",
        "https://www.instagram.com/challenge/",
        password_input_visible=True,
    )

    assert state == "challenge"


def test_story_publish_state_treats_active_upload_as_submitted() -> None:
    assert classify_story_publish_state("Uploading... Add to your story") == "uploading"


def test_story_publish_state_detects_shared_home_state() -> None:
    assert classify_story_publish_state("Home Search Your story Profile") == "success"


def test_story_publish_state_detects_explicit_error() -> None:
    assert classify_story_publish_state("Upload failed. Try again.") == "error"
