from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

STORAGE_ROOT = Path("runtime/storage")
ARTIFACT_ROOT = Path("runtime/artifacts")
BROWSER_PROFILE_ROOT = Path("runtime/profiles")
BROWSER_TIMEOUT_SECONDS = 180
LLM_MODEL = "mistral-large-latest"
COMMAND_PREFIXES = ("/social", "/post", "/status", "/retry", "/accounts")
DEFAULT_ANDROID_ADB_ENDPOINT = "127.0.0.1:5555"


@dataclass(frozen=True)
class PlatformLoginCredentials:
    identifier: str
    password: str
    secondary_identifier: str | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///runtime/media_automata.sqlite3"
    browser_headless: bool = False

    mistral_api_key: str | None = Field(default=None, validation_alias="MISTRAL_API_KEY")
    mistral_api_keys_raw: str | None = Field(default=None, validation_alias="MISTRAL_API_KEYS")
    mistral_api_key1: str | None = Field(default=None, validation_alias="MISTRAL_API_KEY1")
    mistral_api_key2: str | None = Field(default=None, validation_alias="MISTRAL_API_KEY2")
    mistral_api_key3: str | None = Field(default=None, validation_alias="MISTRAL_API_KEY3")

    openwa_base_url: str = Field(default="http://localhost:2785/api", validation_alias="OPENWA_BASE_URL")
    openwa_api_key: str | None = Field(default=None, validation_alias="OPENWA_API_KEY")
    openwa_session_id: str = Field(default="main", validation_alias="OPENWA_SESSION_ID")

    allowed_whatsapp_numbers: str = "*"

    linkedin_email: str | None = Field(default=None, validation_alias="LINKEDIN_EMAIL")
    linkedin_password: str | None = Field(default=None, validation_alias="LINKEDIN_PASSWORD")
    x_login_identifier: str | None = Field(default=None, validation_alias="X_LOGIN_IDENTIFIER")
    x_secondary_identifier: str | None = Field(default=None, validation_alias="X_SECONDARY_IDENTIFIER")
    x_password: str | None = Field(default=None, validation_alias="X_PASSWORD")
    instagram_username: str | None = Field(default=None, validation_alias="INSTAGRAM_USERNAME")
    instagram_password: str | None = Field(default=None, validation_alias="INSTAGRAM_PASSWORD")
    android_device_serial: str | None = Field(default=None, validation_alias="ANDROID_DEVICE_SERIAL")
    android_adb_endpoint: str = Field(default=DEFAULT_ANDROID_ADB_ENDPOINT, validation_alias="ANDROID_ADB_ENDPOINT")
    android_adb_path: str | None = Field(default=None, validation_alias="ANDROID_ADB_PATH")

    @property
    def allowed_numbers(self) -> set[str]:
        values = {item.strip() for item in self.allowed_whatsapp_numbers.split(",") if item.strip()}
        return values or {"*"}

    @property
    def storage_root(self) -> Path:
        return STORAGE_ROOT

    @property
    def artifact_root(self) -> Path:
        return ARTIFACT_ROOT

    @property
    def browser_profile_root(self) -> Path:
        return BROWSER_PROFILE_ROOT

    @property
    def browser_timeout_seconds(self) -> int:
        return BROWSER_TIMEOUT_SECONDS

    @property
    def adb_path(self) -> str:
        configured = self.android_adb_path.strip() if self.android_adb_path else ""
        if configured:
            return configured
        for path in (
            shutil.which("adb"),
            "/home/unichronic/.android-sdk/platform-tools/adb",
        ):
            if path and Path(path).exists():
                return path
        return "adb"

    @property
    def llm_model(self) -> str:
        return LLM_MODEL

    @property
    def mistral_api_keys(self) -> tuple[str, ...]:
        configured_keys: list[str] = []
        if self.mistral_api_keys_raw:
            configured_keys.extend(re.split(r"[\s,;]+", self.mistral_api_keys_raw))
        else:
            for value in (self.mistral_api_key1, self.mistral_api_key2, self.mistral_api_key3):
                if value:
                    configured_keys.append(value)
        if not any(clean_key for clean_key in configured_keys if clean_key):
            if self.mistral_api_key:
                configured_keys.append(self.mistral_api_key)

        keys: list[str] = []
        seen: set[str] = set()
        for value in configured_keys:
            clean_value = value.strip() if value else ""
            if not clean_value or clean_value in seen:
                continue
            seen.add(clean_value)
            keys.append(clean_value)
        return tuple(keys)

    def mistral_api_key_for(self, purpose: str) -> str | None:
        keys = self.mistral_api_keys
        if not keys:
            return None
        return keys[self.mistral_key_index_for(purpose) % len(keys)]

    def mistral_api_keys_for(self, purpose: str) -> tuple[str, ...]:
        keys = self.mistral_api_keys
        if not keys:
            return ()
        start = self.mistral_key_index_for(purpose) % len(keys)
        return keys[start:] + keys[:start]

    @staticmethod
    def mistral_key_index_for(purpose: str) -> int:
        normalized = purpose.lower()
        if "instagram" in normalized:
            return 1
        if "browser" in normalized or "linkedin" in normalized or normalized in {"x", "twitter"}:
            return 2
        return 0

    @property
    def prefixes(self) -> tuple[str, ...]:
        return COMMAND_PREFIXES

    def platform_login_credentials(self, platform: str) -> PlatformLoginCredentials | None:
        if platform == "linkedin":
            return self._credentials(self.linkedin_email, self.linkedin_password)
        if platform == "x":
            return self._credentials(self.x_login_identifier, self.x_password, self.x_secondary_identifier)
        if platform == "instagram":
            return self._credentials(self.instagram_username, self.instagram_password)
        return None

    def ensure_runtime_dirs(self) -> None:
        for path in (self.storage_root, self.artifact_root, self.browser_profile_root):
            path.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            db_path = Path(self.database_url.removeprefix("sqlite:///"))
            db_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _credentials(
        identifier: str | None,
        password: str | None,
        secondary_identifier: str | None = None,
    ) -> PlatformLoginCredentials | None:
        clean_identifier = identifier.strip() if identifier else ""
        clean_password = password.strip() if password else ""
        clean_secondary_identifier = secondary_identifier.strip() if secondary_identifier else ""
        if not clean_identifier or not clean_password:
            return None
        return PlatformLoginCredentials(
            identifier=clean_identifier,
            password=clean_password,
            secondary_identifier=clean_secondary_identifier or None,
        )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_runtime_dirs()
    return settings
