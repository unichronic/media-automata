from media_automata.platforms.instagram import classify_instagram_auth_state, classify_story_publish_state
from media_automata.platforms.instagram_native import instagram_apk_install_candidates


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


def test_instagram_apk_candidates_include_split_and_standalone_apks(tmp_path) -> None:
    old_single = tmp_path / "Instagram_374.apk"
    old_single.write_text("apk", encoding="utf-8")
    split_dir = tmp_path / "instagram-389-x86_64"
    split_dir.mkdir()
    base = split_dir / "com.instagram.android.apk"
    config = split_dir / "config.mdpi.apk"
    base.write_text("base", encoding="utf-8")
    config.write_text("config", encoding="utf-8")

    candidates = instagram_apk_install_candidates(tmp_path)

    assert candidates[0] == [base, config]
    assert [base, config] in candidates
    assert [old_single] in candidates
