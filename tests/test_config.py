from media_automata.config import Settings


def test_platform_login_credentials_are_trimmed(monkeypatch) -> None:
    monkeypatch.setenv("LINKEDIN_EMAIL", " user@example.com ")
    monkeypatch.setenv("LINKEDIN_PASSWORD", " password ")
    monkeypatch.setenv("X_LOGIN_IDENTIFIER", "")
    monkeypatch.setenv("X_PASSWORD", "")

    settings = Settings()

    credentials = settings.platform_login_credentials("linkedin")
    assert credentials is not None
    assert credentials.identifier == "user@example.com"
    assert credentials.password == "password"
    assert credentials.secondary_identifier is None
    assert settings.platform_login_credentials("x") is None


def test_fixed_project_defaults_ignore_old_env_knobs(monkeypatch) -> None:
    monkeypatch.setenv("APP_LLM_MODEL", "wrong-model")
    monkeypatch.setenv("APP_COMMAND_PREFIXES", "/wrong")
    monkeypatch.setenv("APP_BROWSER_TIMEOUT_SECONDS", "1")

    settings = Settings()

    assert settings.llm_model == "mistral-large-latest"
    assert settings.prefixes == ("/help", "/post", "/status", "/retry", "/accounts", "/todo")
    assert settings.browser_timeout_seconds == 180


def test_mistral_keys_are_selected_by_purpose(monkeypatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "legacy")
    monkeypatch.setenv("MISTRAL_API_KEY1", "command-key")
    monkeypatch.setenv("MISTRAL_API_KEY2", "instagram-key")
    monkeypatch.setenv("MISTRAL_API_KEY3", "browser-key")

    settings = Settings()

    assert settings.mistral_api_keys == ("command-key", "instagram-key", "browser-key")
    assert settings.mistral_api_key_for("command") == "command-key"
    assert settings.mistral_api_key_for("browser:instagram") == "instagram-key"
    assert settings.mistral_api_key_for("browser:linkedin") == "browser-key"
    assert settings.mistral_api_key_for("browser:x") == "browser-key"
    assert settings.mistral_api_keys_for("browser:instagram") == (
        "instagram-key",
        "browser-key",
        "command-key",
    )


def test_mistral_keys_can_be_loaded_from_single_list(monkeypatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEYS", "alpha, beta; gamma alpha")
    monkeypatch.setenv("MISTRAL_API_KEY1", "beta")

    settings = Settings()

    assert settings.mistral_api_keys == ("alpha", "beta", "gamma")


def test_x_credentials_include_secondary_identifier(monkeypatch) -> None:
    monkeypatch.setenv("X_LOGIN_IDENTIFIER", " user ")
    monkeypatch.setenv("X_SECONDARY_IDENTIFIER", " email@example.com ")
    monkeypatch.setenv("X_PASSWORD", " password ")

    settings = Settings()

    credentials = settings.platform_login_credentials("x")
    assert credentials is not None
    assert credentials.identifier == "user"
    assert credentials.password == "password"
    assert credentials.secondary_identifier == "email@example.com"
