from media_automata.platforms.profile import persistent_browser_args, prepare_persistent_profile


def test_prepare_persistent_profile_removes_chromium_lockfiles(tmp_path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    lock = profile / "SingletonLock"
    lock.write_text("stale")

    prepare_persistent_profile(profile)

    assert profile.exists()
    assert not lock.exists()


def test_persistent_browser_args_include_stable_session_flags() -> None:
    args = persistent_browser_args()

    assert "--password-store=basic" in args
    assert "--no-first-run" in args
    assert "--window-size=1400,1000" in args
