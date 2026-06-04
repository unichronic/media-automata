from media_automata.platforms.x import classify_x_auth_state


def test_x_auth_prefers_authenticated_controls_over_login_guess() -> None:
    state = classify_x_auth_state(
        "",
        "https://x.com/home",
        login_input_visible=False,
        authenticated_control_visible=True,
    )

    assert state == "authenticated"


def test_x_auth_detects_login_from_flow_url() -> None:
    state = classify_x_auth_state(
        "Sign in to X",
        "https://x.com/i/flow/login",
        login_input_visible=True,
    )

    assert state == "login"


def test_x_auth_treats_empty_home_shell_as_loading() -> None:
    state = classify_x_auth_state(
        "",
        "https://x.com/home",
        login_input_visible=False,
        authenticated_control_visible=False,
    )

    assert state == "loading"
