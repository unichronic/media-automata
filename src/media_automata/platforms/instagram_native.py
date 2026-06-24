from __future__ import annotations

import asyncio
import fcntl
import mimetypes
import queue
import re
import subprocess
import textwrap
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, UnidentifiedImageError

from media_automata.config import Settings
from media_automata.instagram_story_actions import (
    AUTO_FEED_POST_URL,
    INSTAGRAM_STORY_EDITOR_ACTIONS_KEY,
)
from media_automata.platforms.base import WorkerContext
from media_automata.platforms.browser_use_worker import media_paths
from media_automata.schemas import ErrorCode, JobMode, Platform, PlatformContent, PlatformResult, PlatformTaskPayload

INSTAGRAM_ANDROID_PACKAGE = "com.instagram.android"
INSTAGRAM_STORY_SHARE_ACTIVITY = (
    f"{INSTAGRAM_ANDROID_PACKAGE}/com.instagram.share.handleractivity.StoryShareHandlerActivity"
)
INSTAGRAM_CUSTOM_STORY_SHARE_ACTIVITY = (
    f"{INSTAGRAM_ANDROID_PACKAGE}/com.instagram.share.handleractivity.CustomStoryShareHandlerActivity"
)
ANDROID_RUNTIME = "android-native-uiautomator2"
ANDROID_DISPLAY_SIZE = "720x1280"
ANDROID_DISPLAY_DENSITY = "320"
INSTAGRAM_APK_ROOT = Path("runtime/android-apks")
LOGIN_MARKERS = (
    "log in",
    "login",
    "phone number",
    "create new account",
    "remove profiles",
    "you've been logged",
    "you have been logged",
    "logged out",
)
CHALLENGE_MARKERS = (
    "challenge",
    "security code",
    "check your email",
    "enter the code",
    "enter code",
    "confirm",
    "suspicious",
    "verify",
    "verification",
    "captcha",
)
HOME_MARKERS = ("home", "search", "reels", "profile", "your story")
ADD_TO_STORY_MARKERS = (
    "Add post to your story",
    "Add to your story",
    "Add to story",
    "Your story",
)


@dataclass
class AndroidArtifacts:
    screenshots: list[str] = field(default_factory=list)
    hierarchies: list[str] = field(default_factory=list)
    adb_logs: list[str] = field(default_factory=list)


class AndroidRuntimeError(RuntimeError):
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.INTERNAL_ERROR):
        super().__init__(message)
        self.error_code = error_code


def instagram_apk_install_candidates(apk_root: Path = INSTAGRAM_APK_ROOT) -> list[list[Path]]:
    """Return installable Instagram APK bundles from the runtime APK cache.

    Split APK directories are returned as [base, config...] for `adb install-multiple`.
    Standalone APKs at the root are returned as single-file install candidates.
    """

    if not apk_root.exists():
        return []

    candidates: list[tuple[int, float, list[Path]]] = []
    for directory in apk_root.iterdir():
        if not directory.is_dir():
            continue
        base = directory / "com.instagram.android.apk"
        if not base.exists():
            continue
        split_apks = sorted(path for path in directory.glob("*.apk") if path != base)
        candidates.append((0, base.stat().st_mtime, [base, *split_apks]))

    for apk in apk_root.glob("*.apk"):
        candidates.append((1, apk.stat().st_mtime, [apk]))

    return [paths for _, _, paths in sorted(candidates, key=lambda item: (item[0], -item[1]))]


class InstagramNativeWorker:
    """Native Instagram Android automation for features Instagram web does not expose."""

    async def share_latest_feed_post_to_story(
        self,
        payload: PlatformTaskPayload,
        context: WorkerContext,
    ) -> PlatformResult:
        return await asyncio.to_thread(
            self._run_with_native_lock,
            context,
            self._share_latest_feed_post_to_story_sync,
            payload,
            context,
        )

    async def publish_direct_media_story(
        self,
        payload: PlatformTaskPayload,
        context: WorkerContext,
        asset_lookup: dict[str, str],
    ) -> PlatformResult:
        return await asyncio.to_thread(
            self._run_with_native_lock,
            context,
            self._publish_direct_media_story_sync,
            payload,
            context,
            asset_lookup,
        )

    async def check_runtime(self, context: WorkerContext) -> PlatformResult:
        payload = PlatformTaskPayload(
            job_id="android_runtime_check",
            platform=Platform.INSTAGRAM,
            account="main_brand",
            mode=JobMode.PUBLISH,
            content=PlatformContent(
                platform=Platform.INSTAGRAM,
                mode="story",
                extra={"instagram_story_source": "feed_post"},
            ),
        )
        return await asyncio.to_thread(self._run_with_native_lock, context, self._check_runtime_sync, payload, context)

    async def check_auth(self, context: WorkerContext, *, account: str = "main_brand") -> PlatformResult:
        payload = PlatformTaskPayload(
            job_id="android_native_auth_check",
            platform=Platform.INSTAGRAM,
            account=account,
            mode=JobMode.PUBLISH,
            content=PlatformContent(platform=Platform.INSTAGRAM, mode="story"),
        )
        return await asyncio.to_thread(self._run_with_native_lock, context, self._check_auth_sync, payload, context)

    async def login(self, context: WorkerContext, *, account: str = "main_brand") -> PlatformResult:
        payload = PlatformTaskPayload(
            job_id="android_native_login",
            platform=Platform.INSTAGRAM,
            account=account,
            mode=JobMode.PUBLISH,
            content=PlatformContent(platform=Platform.INSTAGRAM, mode="story"),
        )
        return await asyncio.to_thread(self._run_with_native_lock, context, self._login_sync, payload, context)

    async def backup_app_data(self, context: WorkerContext, *, account: str = "main_brand") -> PlatformResult:
        payload = PlatformTaskPayload(
            job_id="android_native_backup",
            platform=Platform.INSTAGRAM,
            account=account,
            mode=JobMode.PUBLISH,
            content=PlatformContent(platform=Platform.INSTAGRAM, mode="story"),
        )
        return await asyncio.to_thread(
            self._run_with_native_lock,
            context,
            self._backup_app_data_sync,
            payload,
            context,
        )

    async def restore_app_data(
        self,
        context: WorkerContext,
        *,
        backup_path: str | None = None,
        account: str = "main_brand",
    ) -> PlatformResult:
        payload = PlatformTaskPayload(
            job_id="android_native_restore",
            platform=Platform.INSTAGRAM,
            account=account,
            mode=JobMode.PUBLISH,
            content=PlatformContent(platform=Platform.INSTAGRAM, mode="story"),
        )
        return await asyncio.to_thread(
            self._run_with_native_lock,
            context,
            self._restore_app_data_sync,
            payload,
            context,
            backup_path,
        )

    async def enter_verification_code(
        self,
        code: str,
        context: WorkerContext,
        *,
        account: str = "main_brand",
        job_id: str = "android_instagram_code",
    ) -> PlatformResult:
        payload = PlatformTaskPayload(
            job_id=job_id,
            platform=Platform.INSTAGRAM,
            account=account,
            mode=JobMode.PUBLISH,
            content=PlatformContent(platform=Platform.INSTAGRAM, mode="story"),
        )
        return await asyncio.to_thread(
            self._run_with_native_lock,
            context,
            self._enter_verification_code_sync,
            code,
            payload,
            context,
        )

    def _run_with_native_lock(self, context: WorkerContext, func: Any, *args: Any) -> PlatformResult:
        lock_path = context.settings.artifact_root.parent / "android-native.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("w", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                return func(*args)
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    def _check_runtime_sync(self, payload: PlatformTaskPayload, context: WorkerContext) -> PlatformResult:
        artifacts = AndroidArtifacts()
        try:
            device, serial = self._connect_device(context.settings, artifacts)
            self._ensure_instagram_installed(context.settings, serial)
            self._capture(device, context, payload, "runtime-check", artifacts)
            return PlatformResult(
                platform=payload.platform,
                status="success",
                message=f"Android runtime is reachable and {INSTAGRAM_ANDROID_PACKAGE} is installed.",
                raw=self._raw(artifacts, serial=serial, auth_status="unknown"),
            )
        except AndroidRuntimeError as exc:
            return self._failed(payload, str(exc), exc.error_code, artifacts)
        except Exception as exc:
            return self._failed(payload, f"Android runtime check crashed: {exc}", ErrorCode.INTERNAL_ERROR, artifacts)

    def _check_auth_sync(self, payload: PlatformTaskPayload, context: WorkerContext) -> PlatformResult:
        artifacts = AndroidArtifacts()
        serial = context.settings.android_device_serial or context.settings.android_adb_endpoint
        try:
            device, serial = self._connect_device(context.settings, artifacts)
            self._ensure_instagram_installed(context.settings, serial)
            self._start_instagram(device, context.settings, serial)
            self._wait(3)
            self._dismiss_popups(device)
            self._capture(device, context, payload, "native-auth-state", artifacts)
            auth_status = self._classify_native_auth_state(device)
            messages = {
                "authenticated": "Instagram Android native app is authenticated.",
                "challenge_required": "Instagram Android native app is waiting for manual verification.",
                "login_required": "Instagram Android native app is logged out.",
                "app_not_foreground": "Instagram Android native app is not foreground after launch.",
            }
            status = "success" if auth_status == "authenticated" else "failed"
            error_code = None
            if auth_status == "challenge_required":
                error_code = ErrorCode.CAPTCHA_OR_VERIFICATION
            elif auth_status == "login_required":
                error_code = ErrorCode.LOGIN_REQUIRED
            elif auth_status != "authenticated":
                error_code = ErrorCode.INTERNAL_ERROR
            return PlatformResult(
                platform=payload.platform,
                status=status,
                message=messages.get(auth_status, f"Instagram Android native auth state is {auth_status}."),
                error_code=error_code,
                raw=self._raw(artifacts, serial=serial, auth_status=auth_status),
            )
        except AndroidRuntimeError as exc:
            return self._failed(payload, str(exc), exc.error_code, artifacts, serial=serial)
        except Exception as exc:
            return self._failed(
                payload,
                f"Instagram native auth check crashed: {exc}",
                ErrorCode.INTERNAL_ERROR,
                artifacts,
                serial=serial,
            )

    def _login_sync(self, payload: PlatformTaskPayload, context: WorkerContext) -> PlatformResult:
        artifacts = AndroidArtifacts()
        serial = context.settings.android_device_serial or context.settings.android_adb_endpoint
        try:
            device, serial = self._connect_device(context.settings, artifacts)
            self._ensure_instagram_installed(context.settings, serial)
            self._start_instagram(device, context.settings, serial)
            self._wait(3)
            self._dismiss_popups(device)
            self._capture(device, context, payload, "native-login-start", artifacts)
            auth_status = self._ensure_authenticated_with_recovery(
                device,
                context.settings,
                serial,
                context,
                payload,
                artifacts,
            )
            self._capture(device, context, payload, "native-login-final", artifacts)
            if auth_status == "authenticated":
                raw = self._raw(artifacts, serial=serial, auth_status=auth_status)
                message = "Instagram Android native app is authenticated."
                try:
                    local_path, latest_path = self._create_app_data_backup(
                        context.settings,
                        serial,
                        payload,
                        artifacts,
                    )
                    message = f"{message} Android app data snapshot saved to {latest_path}."
                    raw = {
                        **self._raw(artifacts, serial=serial, auth_status=auth_status),
                        "backup_path": str(local_path),
                        "latest_backup_path": str(latest_path),
                    }
                except Exception as backup_exc:
                    artifacts.adb_logs.append(f"native-login-backup-failed: {backup_exc}")
                    raw = self._raw(artifacts, serial=serial, auth_status=auth_status)
                return PlatformResult(
                    platform=payload.platform,
                    status="success",
                    message=message,
                    raw=raw,
                )
            if auth_status == "challenge_required":
                return self._failed(
                    payload,
                    "Instagram Android native login is waiting for manual verification.",
                    ErrorCode.CAPTCHA_OR_VERIFICATION,
                    artifacts,
                    serial=serial,
                    auth_status=auth_status,
                )
            if auth_status == "app_not_foreground":
                return self._failed(
                    payload,
                    "Instagram Android app is not foreground after launch; the app may have crashed or failed to open.",
                    ErrorCode.INTERNAL_ERROR,
                    artifacts,
                    serial=serial,
                    auth_status=auth_status,
                )
            return self._failed(
                payload,
                "Instagram Android native login is required and could not be completed automatically.",
                ErrorCode.LOGIN_REQUIRED,
                artifacts,
                serial=serial,
                auth_status=auth_status,
            )
        except AndroidRuntimeError as exc:
            return self._failed(payload, str(exc), exc.error_code, artifacts, serial=serial)
        except Exception as exc:
            return self._failed(
                payload,
                f"Instagram native login crashed: {exc}",
                ErrorCode.INTERNAL_ERROR,
                artifacts,
                serial=serial,
            )

    def _backup_app_data_sync(self, payload: PlatformTaskPayload, context: WorkerContext) -> PlatformResult:
        artifacts = AndroidArtifacts()
        serial = context.settings.android_device_serial or context.settings.android_adb_endpoint
        try:
            device, serial = self._connect_device(context.settings, artifacts)
            self._ensure_instagram_installed(context.settings, serial)
            self._start_instagram(device, context.settings, serial)
            self._wait(3)
            self._dismiss_popups(device)
            auth_status = self._classify_native_auth_state(device)
            if auth_status != "authenticated":
                self._capture(device, context, payload, "backup-auth-not-ready", artifacts)
                return self._failed(
                    payload,
                    "Refusing to back up Instagram Android data before native auth is authenticated.",
                    ErrorCode.LOGIN_REQUIRED
                    if auth_status == "login_required"
                    else ErrorCode.CAPTCHA_OR_VERIFICATION
                    if auth_status == "challenge_required"
                    else ErrorCode.INTERNAL_ERROR,
                    artifacts,
                    serial=serial,
                    auth_status=auth_status,
                )
            local_path, latest_path = self._create_app_data_backup(context.settings, serial, payload, artifacts)
            return PlatformResult(
                platform=payload.platform,
                status="success",
                message=f"Instagram Android app data backed up to {latest_path}.",
                raw={
                    **self._raw(artifacts, serial=serial, auth_status=auth_status),
                    "backup_path": str(local_path),
                    "latest_backup_path": str(latest_path),
                },
            )
        except AndroidRuntimeError as exc:
            return self._failed(payload, str(exc), exc.error_code, artifacts, serial=serial)
        except Exception as exc:
            return self._failed(
                payload,
                f"Instagram Android backup crashed: {exc}",
                ErrorCode.INTERNAL_ERROR,
                artifacts,
                serial=serial,
            )

    def _restore_app_data_sync(
        self,
        payload: PlatformTaskPayload,
        context: WorkerContext,
        backup_path: str | None,
    ) -> PlatformResult:
        artifacts = AndroidArtifacts()
        serial = context.settings.android_device_serial or context.settings.android_adb_endpoint
        backup = Path(backup_path) if backup_path else self._latest_backup_path(payload.account)
        if not backup.exists():
            return self._failed(
                payload,
                f"Instagram Android backup was not found at {backup}.",
                ErrorCode.INTERNAL_ERROR,
                artifacts,
                serial=serial,
                auth_status="not_started",
            )
        try:
            device, serial = self._connect_device(context.settings, artifacts)
            self._ensure_instagram_installed(context.settings, serial)
            self._restore_app_data_files(context.settings, serial, backup, artifacts)
            self._start_instagram(device, context.settings, serial)
            self._wait(5)
            self._dismiss_popups(device)
            self._capture(device, context, payload, "restore-auth-state", artifacts)
            auth_status = self._classify_native_auth_state(device)
            if auth_status != "authenticated" and context.settings.platform_login_credentials("instagram"):
                artifacts.adb_logs.append(
                    f"restore-auth-state={auth_status}; clearing app data and using credential login fallback"
                )
                self._fresh_login_after_restore(device, context.settings, serial, context, payload, artifacts)
                auth_status = self._classify_native_auth_state(device)
                if auth_status == "authenticated":
                    try:
                        local_path, latest_path = self._create_app_data_backup(
                            context.settings,
                            serial,
                            payload,
                            artifacts,
                        )
                        artifacts.adb_logs.append(
                            f"fresh-login-backup-saved: {local_path} latest={latest_path}"
                        )
                    except Exception as backup_exc:
                        artifacts.adb_logs.append(f"fresh-login-backup-failed: {backup_exc}")
            return PlatformResult(
                platform=payload.platform,
                status="success" if auth_status == "authenticated" else "failed",
                message=(
                    "Instagram Android app data restored or refreshed and native auth is authenticated."
                    if auth_status == "authenticated"
                    else f"Instagram Android app data restored, but native auth is {auth_status}."
                ),
                error_code=None
                if auth_status == "authenticated"
                else ErrorCode.CAPTCHA_OR_VERIFICATION
                if auth_status == "challenge_required"
                else ErrorCode.LOGIN_REQUIRED,
                raw={
                    **self._raw(artifacts, serial=serial, auth_status=auth_status),
                    "backup_path": str(backup),
                },
            )
        except AndroidRuntimeError as exc:
            return self._failed(payload, str(exc), exc.error_code, artifacts, serial=serial)
        except Exception as exc:
            return self._failed(
                payload,
                f"Instagram Android restore crashed: {exc}",
                ErrorCode.INTERNAL_ERROR,
                artifacts,
                serial=serial,
            )

    def _enter_verification_code_sync(
        self,
        code: str,
        payload: PlatformTaskPayload,
        context: WorkerContext,
    ) -> PlatformResult:
        artifacts = AndroidArtifacts()
        serial = context.settings.android_device_serial or context.settings.android_adb_endpoint
        clean_code = re.sub(r"\D+", "", code)
        if not clean_code:
            return self._failed(
                payload,
                "Instagram verification code must contain digits.",
                ErrorCode.CONTENT_REJECTED,
                artifacts,
                serial=serial,
                auth_status="challenge_required",
            )
        try:
            device, serial = self._connect_device(context.settings, artifacts)
            self._ensure_instagram_installed(context.settings, serial)
            if not self._is_instagram_foreground(device):
                self._start_instagram(device, context.settings, serial)
            self._capture(device, context, payload, "code-before-submit", artifacts)
            if not self._submit_verification_code(device, clean_code, context, payload, artifacts):
                return self._failed(
                    payload,
                    "Instagram verification code field or continue button was not found.",
                    ErrorCode.COMPOSER_NOT_FOUND,
                    artifacts,
                    serial=serial,
                    auth_status="challenge_required",
                )
            for _ in range(45):
                self._wait(2)
                self._dismiss_popups(device)
                text = self._hierarchy(device).lower()
                if "error during code validation" in text or "incorrect code" in text or "invalid code" in text:
                    self._capture(device, context, payload, "code-validation-error", artifacts)
                    return self._failed(
                        payload,
                        "Instagram rejected the verification code.",
                        ErrorCode.CAPTCHA_OR_VERIFICATION,
                        artifacts,
                        serial=serial,
                        auth_status="challenge_required",
                    )
                if self._is_instagram_foreground(device) and self._looks_authenticated(text):
                    self._capture(device, context, payload, "code-authenticated", artifacts)
                    message = "Instagram Android verification code accepted; account is authenticated."
                    raw = self._raw(artifacts, serial=serial, auth_status="authenticated")
                    try:
                        local_path, latest_path = self._create_app_data_backup(
                            context.settings,
                            serial,
                            payload,
                            artifacts,
                        )
                        message = f"{message} Android app data snapshot saved to {latest_path}."
                        raw = {
                            **self._raw(artifacts, serial=serial, auth_status="authenticated"),
                            "backup_path": str(local_path),
                            "latest_backup_path": str(latest_path),
                        }
                    except Exception as backup_exc:
                        artifacts.adb_logs.append(f"post-auth-backup-failed: {backup_exc}")
                        raw = self._raw(artifacts, serial=serial, auth_status="authenticated")
                    return PlatformResult(
                        platform=payload.platform,
                        status="success",
                        message=message,
                        raw=raw,
                    )
                if any(marker in text for marker in CHALLENGE_MARKERS):
                    continue
            self._capture(device, context, payload, "code-submit-timeout", artifacts)
            return self._failed(
                payload,
                "Instagram verification code was submitted, but authenticated UI did not appear before timeout.",
                ErrorCode.CAPTCHA_OR_VERIFICATION,
                artifacts,
                serial=serial,
                auth_status="challenge_required",
            )
        except AndroidRuntimeError as exc:
            return self._failed(payload, str(exc), exc.error_code, artifacts, serial=serial)
        except Exception as exc:
            return self._failed(
                payload,
                f"Instagram verification helper crashed: {exc}",
                ErrorCode.INTERNAL_ERROR,
                artifacts,
                serial=serial,
            )

    def _publish_direct_media_story_sync(
        self,
        payload: PlatformTaskPayload,
        context: WorkerContext,
        asset_lookup: dict[str, str],
    ) -> PlatformResult:
        artifacts = AndroidArtifacts()
        serial = context.settings.android_device_serial or context.settings.android_adb_endpoint
        media = media_paths(payload, context, asset_lookup)
        if not media:
            return self._failed(
                payload,
                "Instagram native Story publishing requires at least one media asset.",
                ErrorCode.CONTENT_REJECTED,
                artifacts,
                serial=serial,
                auth_status="not_started",
            )
        media_path, action_payload = self._pre_render_direct_story_text_overlays(media[0], payload, context, artifacts)

        try:
            device, serial = self._connect_device(context.settings, artifacts)
            self._ensure_instagram_installed(context.settings, serial)
            self._grant_instagram_permissions(context.settings, serial, artifacts)
            self._adb(
                context.settings,
                ["-s", serial, "shell", "am", "force-stop", INSTAGRAM_ANDROID_PACKAGE],
                timeout=20,
            )
            self._wait(1)
            self._start_instagram(device, context.settings, serial)
            self._dismiss_popups(device)
            self._capture(device, context, payload, "direct-story-start", artifacts)

            auth_status = self._ensure_authenticated_with_recovery(
                device,
                context.settings,
                serial,
                context,
                payload,
                artifacts,
            )
            if auth_status == "challenge_required":
                return self._failed(
                    payload,
                    "Instagram Android app requires manual verification before native Story publishing.",
                    ErrorCode.CAPTCHA_OR_VERIFICATION,
                    artifacts,
                    serial=serial,
                    auth_status=auth_status,
                )
            if auth_status == "app_not_foreground":
                return self._failed(
                    payload,
                    "Instagram Android app is not foreground after launch; the app may have crashed or failed to open.",
                    ErrorCode.INTERNAL_ERROR,
                    artifacts,
                    serial=serial,
                    auth_status=auth_status,
                )
            if auth_status != "authenticated":
                return self._failed(
                    payload,
                    "Instagram Android app login is required before native Story publishing.",
                    ErrorCode.LOGIN_REQUIRED,
                    artifacts,
                    serial=serial,
                    auth_status=auth_status,
                )

            self._grant_instagram_permissions(context.settings, serial, artifacts)
            if not self._open_direct_media_story_editor(
                device,
                context.settings,
                serial,
                media_path,
                context,
                payload,
                artifacts,
            ):
                return self._failed(
                    payload,
                    "Could not open Instagram native Story editor with the provided media.",
                    ErrorCode.COMPOSER_NOT_FOUND,
                    artifacts,
                    serial=serial,
                    auth_status=auth_status,
                )

            self._apply_story_editor_actions(device, context.settings, serial, context, action_payload, artifacts)
            if not self._publish_story(device, context, payload, artifacts):
                return self._failed(
                    payload,
                    "Native Instagram Story publish control was not found.",
                    ErrorCode.PUBLISH_BUTTON_DISABLED,
                    artifacts,
                    serial=serial,
                    auth_status=auth_status,
                )
            return PlatformResult(
                platform=payload.platform,
                status="success",
                message="Instagram native Story shared.",
                raw=self._raw(artifacts, serial=serial, auth_status=auth_status),
            )
        except AndroidRuntimeError as exc:
            return self._failed(payload, str(exc), exc.error_code, artifacts, serial=serial)
        except Exception as exc:
            return self._failed(
                payload,
                f"Instagram native direct Story worker crashed: {exc}",
                ErrorCode.INTERNAL_ERROR,
                artifacts,
                serial=serial,
            )

    def _share_latest_feed_post_to_story_sync(
        self,
        payload: PlatformTaskPayload,
        context: WorkerContext,
    ) -> PlatformResult:
        artifacts = AndroidArtifacts()
        serial = context.settings.android_device_serial or context.settings.android_adb_endpoint
        target_post_url = self._target_post_url(payload)
        try:
            device, serial = self._connect_device(context.settings, artifacts)
            self._ensure_instagram_installed(context.settings, serial)
            self._grant_instagram_permissions(context.settings, serial, artifacts)
            self._adb(
                context.settings,
                ["-s", serial, "shell", "am", "force-stop", INSTAGRAM_ANDROID_PACKAGE],
                timeout=20,
            )
            self._wait(1)
            if target_post_url:
                self._open_post_url(device, context.settings, serial, target_post_url)
            else:
                self._open_profile(device, context.settings, serial)
            self._wait(4)
            self._dismiss_popups(device)
            opened_capture_name = "post-url-opened" if target_post_url else "profile-opened"
            self._capture(device, context, payload, opened_capture_name, artifacts)

            auth_status = self._ensure_authenticated_with_recovery(
                device,
                context.settings,
                serial,
                context,
                payload,
                artifacts,
            )
            if auth_status == "challenge_required":
                return self._failed(
                    payload,
                    "Instagram Android app requires manual verification before feed-post Story sharing.",
                    ErrorCode.CAPTCHA_OR_VERIFICATION,
                    artifacts,
                    serial=serial,
                    auth_status=auth_status,
                )
            if auth_status == "app_not_foreground":
                return self._failed(
                    payload,
                    "Instagram Android app is not foreground after launch; the app may have crashed or failed to open.",
                    ErrorCode.INTERNAL_ERROR,
                    artifacts,
                    serial=serial,
                    auth_status=auth_status,
                )
            if auth_status != "authenticated":
                return self._failed(
                    payload,
                    "Instagram Android app login is required before feed-post Story sharing.",
                    ErrorCode.LOGIN_REQUIRED,
                    artifacts,
                    serial=serial,
                    auth_status=auth_status,
                )

            self._grant_instagram_permissions(context.settings, serial, artifacts)
            self._dismiss_popups(device)
            if target_post_url:
                self._open_post_url(device, context.settings, serial, target_post_url)
                self._wait(5)
                self._capture(device, context, payload, "target-post-opened", artifacts)
                post_opened = self._is_instagram_foreground(device) and self._screen_has_any(
                    device, ("like", "comment", "share", "send")
                )
            else:
                self._open_own_profile_tab(device, context, payload, artifacts)
                post_opened = self._open_latest_post(device, context, payload, artifacts)
            if not post_opened:
                return self._failed(
                    payload,
                    "Could not open the latest Instagram profile post in the Android app.",
                    ErrorCode.COMPOSER_NOT_FOUND,
                    artifacts,
                    serial=serial,
                    auth_status=auth_status,
                )

            if not self._open_share_sheet(device, context, payload, artifacts):
                return self._failed(
                    payload,
                    "Could not open the native Instagram post share sheet.",
                    ErrorCode.COMPOSER_NOT_FOUND,
                    artifacts,
                    serial=serial,
                    auth_status=auth_status,
                )

            if not self._click_add_to_story(device, context, payload, artifacts):
                return self._failed(
                    payload,
                    "Native Instagram share sheet did not expose an Add to Story control.",
                    ErrorCode.COMPOSER_NOT_FOUND,
                    artifacts,
                    serial=serial,
                    auth_status=auth_status,
                )

            self._apply_story_editor_actions(device, context.settings, serial, context, payload, artifacts)
            if not self._publish_story(device, context, payload, artifacts):
                return self._failed(
                    payload,
                    "Native Instagram Story publish control was not found.",
                    ErrorCode.PUBLISH_BUTTON_DISABLED,
                    artifacts,
                    serial=serial,
                    auth_status=auth_status,
                )

            return PlatformResult(
                platform=payload.platform,
                status="success",
                message="Instagram latest feed post was shared to Story through the native Android app.",
                raw=self._raw(artifacts, serial=serial, auth_status=auth_status),
            )
        except AndroidRuntimeError as exc:
            return self._failed(payload, str(exc), exc.error_code, artifacts, serial=serial)
        except Exception as exc:
            return self._failed(
                payload,
                f"Instagram native Android worker crashed: {exc}",
                ErrorCode.INTERNAL_ERROR,
                artifacts,
                serial=serial,
            )

    def _connect_device(self, settings: Settings, artifacts: AndroidArtifacts) -> tuple[Any, str]:
        try:
            import uiautomator2 as u2
        except Exception as exc:  # pragma: no cover - exercised when optional dependency is absent
            raise AndroidRuntimeError(
                f"uiautomator2 is not installed: {exc}. Install project dependencies before native Android runs."
            ) from exc

        serial = settings.android_device_serial or settings.android_adb_endpoint
        if not serial:
            raise AndroidRuntimeError("ANDROID_DEVICE_SERIAL or ANDROID_ADB_ENDPOINT must identify an ADB device.")

        if not settings.android_device_serial and settings.android_adb_endpoint:
            completed = self._adb(settings, ["connect", settings.android_adb_endpoint], timeout=20)
            artifacts.adb_logs.append(completed.stdout.strip() or completed.stderr.strip())

        try:
            device = u2.connect(serial)
            _ = device.info
            self._configure_android_display(settings, serial, artifacts)
            return device, serial
        except Exception as exc:
            raise AndroidRuntimeError(f"Could not connect to Android device {serial}: {exc}") from exc

    def _configure_android_display(self, settings: Settings, serial: str, artifacts: AndroidArtifacts) -> None:
        commands = (
            ("wm", "size", ANDROID_DISPLAY_SIZE),
            ("wm", "density", ANDROID_DISPLAY_DENSITY),
            ("settings", "put", "system", "font_scale", "0.85"),
        )
        for command in commands:
            completed = self._adb(settings, ["-s", serial, "shell", *command], timeout=10)
            output = (completed.stdout.strip() or completed.stderr.strip()).strip()
            if output and "error" not in output.lower():
                artifacts.adb_logs.append(output)

    def _ensure_instagram_installed(self, settings: Settings, serial: str) -> None:
        completed = self._adb(settings, ["-s", serial, "shell", "pm", "path", INSTAGRAM_ANDROID_PACKAGE], timeout=20)
        output = f"{completed.stdout}\n{completed.stderr}".strip()
        if completed.returncode == 0 and "package:" in output:
            return

        install_errors: list[str] = []
        for candidate in instagram_apk_install_candidates():
            command = ["install-multiple", "-r", *[str(path) for path in candidate]]
            if len(candidate) == 1:
                command = ["install", "-r", str(candidate[0])]
            installed = self._adb(settings, ["-s", serial, *command], timeout=300)
            install_output = f"{installed.stdout}\n{installed.stderr}".strip()
            if installed.returncode == 0 and "success" in install_output.lower():
                verified = self._adb(
                    settings,
                    ["-s", serial, "shell", "pm", "path", INSTAGRAM_ANDROID_PACKAGE],
                    timeout=20,
                )
                verified_output = f"{verified.stdout}\n{verified.stderr}".strip()
                if verified.returncode == 0 and "package:" in verified_output:
                    return
            install_errors.append(install_output[:500] or f"install returned {installed.returncode}")

        if install_errors:
            detail = " Last install error: " + install_errors[-1]
        else:
            detail = f" No APK bundle was found under {INSTAGRAM_APK_ROOT}."
        raise AndroidRuntimeError(
            f"{INSTAGRAM_ANDROID_PACKAGE} is not installed on Android device {serial}.{detail}",
            ErrorCode.LOGIN_REQUIRED,
        )

    def _grant_instagram_permissions(self, settings: Settings, serial: str, artifacts: AndroidArtifacts) -> None:
        permissions = (
            "android.permission.CAMERA",
            "android.permission.RECORD_AUDIO",
            "android.permission.READ_EXTERNAL_STORAGE",
            "android.permission.WRITE_EXTERNAL_STORAGE",
            "android.permission.READ_MEDIA_IMAGES",
            "android.permission.READ_MEDIA_VIDEO",
            "android.permission.READ_MEDIA_VISUAL_USER_SELECTED",
        )
        for permission in permissions:
            completed = self._adb(
                settings,
                ["-s", serial, "shell", "pm", "grant", INSTAGRAM_ANDROID_PACKAGE, permission],
                timeout=10,
            )
            output = (completed.stdout.strip() or completed.stderr.strip()).strip()
            if output and "Unknown permission" not in output and "not a changeable permission type" not in output:
                artifacts.adb_logs.append(output)
        app_ops = (
            "READ_EXTERNAL_STORAGE",
            "WRITE_EXTERNAL_STORAGE",
            "READ_MEDIA_IMAGES",
            "READ_MEDIA_VIDEO",
            "READ_MEDIA_VISUAL_USER_SELECTED",
            "CAMERA",
            "RECORD_AUDIO",
        )
        for app_op in app_ops:
            completed = self._adb(
                settings,
                ["-s", serial, "shell", "appops", "set", INSTAGRAM_ANDROID_PACKAGE, app_op, "allow"],
                timeout=10,
            )
            output = (completed.stdout.strip() or completed.stderr.strip()).strip()
            if output and "Unknown operation" not in output and "Error" not in output:
                artifacts.adb_logs.append(output)

    def _open_profile(self, device: Any, settings: Settings, serial: str) -> None:
        username = (settings.instagram_username or "").strip().lstrip("@")
        self._start_instagram(device, settings, serial)
        if username:
            url = f"https://www.instagram.com/{quote(username)}/"
            self._adb(
                settings,
                [
                    "-s",
                    serial,
                    "shell",
                    "am",
                    "start",
                    "-a",
                    "android.intent.action.VIEW",
                    "-d",
                    url,
                    "-p",
                    INSTAGRAM_ANDROID_PACKAGE,
                ],
                timeout=25,
            )
            self._wait(3)
        if not self._is_instagram_foreground(device):
            self._start_instagram(device, settings, serial)

    def _open_post_url(self, device: Any, settings: Settings, serial: str, url: str) -> None:
        self._start_instagram(device, settings, serial)
        self._adb(
            settings,
            [
                "-s",
                serial,
                "shell",
                "am",
                "start",
                "-a",
                "android.intent.action.VIEW",
                "-d",
                url,
                "-p",
                INSTAGRAM_ANDROID_PACKAGE,
            ],
            timeout=25,
        )
        self._wait(2)
        if not self._is_instagram_foreground(device):
            self._start_instagram(device, settings, serial)

    def _ensure_authenticated(
        self,
        device: Any,
        settings: Settings,
        context: WorkerContext,
        payload: PlatformTaskPayload,
        artifacts: AndroidArtifacts,
    ) -> str:
        hierarchy = self._hierarchy(device)
        text = hierarchy.lower()
        if not self._is_instagram_foreground(device):
            self._capture(device, context, payload, "instagram-not-foreground", artifacts)
            return "app_not_foreground"
        if any(marker in text for marker in CHALLENGE_MARKERS):
            return "challenge_required"
        if self._story_composer_visible_text(text):
            return "authenticated"
        if self._looks_authenticated(text):
            return "authenticated"

        credentials = settings.platform_login_credentials("instagram")
        if not credentials:
            return "login_required"

        self._click_login_entrypoint(device)
        self._wait(3)
        text = self._hierarchy(device).lower()
        if any(marker in text for marker in CHALLENGE_MARKERS):
            self._capture(device, context, payload, "login-challenge", artifacts)
            return "challenge_required"
        if self._looks_authenticated(text):
            self._capture(device, context, payload, "login-authenticated-from-saved-profile", artifacts)
            return "authenticated"
        if not self._wait_for_login_form(device, timeout=10):
            self._capture(device, context, payload, "login-form-not-found", artifacts)
            return "login_required"
        for login_attempt in range(3):
            self._fill_login_form(device, credentials.identifier, credentials.password)
            capture_name = "login-filled" if login_attempt == 0 else f"login-filled-retry-{login_attempt + 1}"
            self._capture(device, context, payload, capture_name, artifacts)
            if not self._click_login_submit_button(device, timeout=5):
                width, height = self._display_size(device)
                device.click(width // 2, int(height * 0.66))
                self._wait(1)
                if self._screen_has_any(device, ("username, email", "password")):
                    self._press_enter(device)
            relaunched_after_submit = False
            for _ in range(15):
                self._wait(2)
                self._dismiss_popups(device)
                hierarchy = self._hierarchy(device)
                text = hierarchy.lower()
                if not self._is_instagram_foreground(device):
                    if not relaunched_after_submit:
                        try:
                            device.app_start(INSTAGRAM_ANDROID_PACKAGE, wait=True)
                        except Exception:
                            pass
                        relaunched_after_submit = True
                        self._wait(3)
                        continue
                    self._capture(device, context, payload, "login-app-not-foreground", artifacts)
                    return "app_not_foreground"
                if any(marker in text for marker in CHALLENGE_MARKERS):
                    self._capture(device, context, payload, "login-challenge", artifacts)
                    return "challenge_required"
                if self._story_composer_visible_text(text) or self._looks_authenticated(text):
                    self._capture(device, context, payload, "login-authenticated", artifacts)
                    return "authenticated"
                if (
                    "android.widget.edittext" in text
                    and ("username" in text or "email" in text)
                    and "password" in text
                    and credentials.identifier.lower() not in text
                    and login_attempt < 2
                ):
                    artifacts.adb_logs.append(f"instagram-login-form-reset-after-attempt-{login_attempt + 1}")
                    break
        self._capture(device, context, payload, "login-timeout", artifacts)
        return "login_required"

    def _ensure_authenticated_with_recovery(
        self,
        device: Any,
        settings: Settings,
        serial: str,
        context: WorkerContext,
        payload: PlatformTaskPayload,
        artifacts: AndroidArtifacts,
    ) -> str:
        auth_status = self._ensure_authenticated(device, settings, context, payload, artifacts)
        if auth_status == "authenticated" or auth_status == "challenge_required":
            return auth_status

        if settings.platform_login_credentials("instagram"):
            artifacts.adb_logs.append(f"native-auth={auth_status}; using fresh credential login recovery")
            fresh_status = self._fresh_login_after_restore(device, settings, serial, context, payload, artifacts)
            if fresh_status == "authenticated":
                try:
                    _, latest_path = self._create_app_data_backup(settings, serial, payload, artifacts)
                    artifacts.adb_logs.append(f"native-fresh-login-backup-saved: {latest_path}")
                except Exception as backup_exc:
                    artifacts.adb_logs.append(f"native-fresh-login-backup-failed: {backup_exc}")
                return fresh_status
            if fresh_status == "challenge_required":
                return fresh_status
            return fresh_status

        backup = self._latest_backup_path(payload.account)
        if backup.exists():
            artifacts.adb_logs.append(f"native-auth={auth_status}; restoring Android app data from {backup}")
            try:
                self._restore_app_data_files(settings, serial, backup, artifacts)
                self._start_instagram(device, settings, serial)
                self._wait(5)
                self._dismiss_popups(device)
                self._capture(device, context, payload, "auth-after-auto-restore", artifacts)
                restored_status = self._ensure_authenticated(device, settings, context, payload, artifacts)
                if restored_status == "authenticated" or restored_status == "challenge_required":
                    return restored_status
                auth_status = restored_status
            except AndroidRuntimeError as exc:
                artifacts.adb_logs.append(f"native-auto-restore-failed: {exc}")
        else:
            artifacts.adb_logs.append(f"no-native-auth-backup-found: {backup}")

        return auth_status

    def _fresh_login_after_restore(
        self,
        device: Any,
        settings: Settings,
        serial: str,
        context: WorkerContext,
        payload: PlatformTaskPayload,
        artifacts: AndroidArtifacts,
    ) -> str:
        self._adb(settings, ["-s", serial, "shell", "am", "force-stop", INSTAGRAM_ANDROID_PACKAGE], timeout=20)
        self._adb(settings, ["-s", serial, "shell", "pm", "clear", INSTAGRAM_ANDROID_PACKAGE], timeout=60)
        self._start_instagram(device, settings, serial)
        self._wait_for_instagram_after_clear(device, settings, serial, artifacts)
        self._dismiss_popups(device)
        self._capture(device, context, payload, "fresh-login-start", artifacts)
        auth_status = self._ensure_authenticated(device, settings, context, payload, artifacts)
        self._capture(device, context, payload, "fresh-login-final", artifacts)
        return auth_status

    def _wait_for_instagram_after_clear(
        self,
        device: Any,
        settings: Settings,
        serial: str,
        artifacts: AndroidArtifacts,
    ) -> None:
        restarted = False
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            self._wait(2)
            if not self._is_instagram_foreground(device):
                if not restarted:
                    self._start_instagram(device, settings, serial)
                    restarted = True
                    continue
                return
            text = self._hierarchy(device).lower()
            if (
                self._looks_authenticated(text)
                or any(marker in text for marker in CHALLENGE_MARKERS)
                or "android.widget.edittext" in text
                or "profile photo" in text
                or "log in" in text
                or "login" in text
            ):
                return
            if "instagram from meta" in text and not restarted and time.monotonic() > deadline - 25:
                artifacts.adb_logs.append("instagram-clear-start-stuck-on-splash; force-stopping and relaunching")
                self._adb(
                    settings,
                    ["-s", serial, "shell", "am", "force-stop", INSTAGRAM_ANDROID_PACKAGE],
                    timeout=20,
                )
                self._start_instagram(device, settings, serial)
                restarted = True

    def _click_login_entrypoint(self, device: Any) -> None:
        if self._wait_for_login_form(device, timeout=2):
            return
        if self._click_saved_profile_entrypoint(device):
            return
        if self._click_any_text(
            device,
            [
                "I already have a profile",
                "I already have an account",
                "Already have an account?",
                "Log in",
                "Log In",
                "Login",
            ],
            timeout=4,
        ) or self._click_any_description(
            device,
            [
                "I already have a profile",
                "I already have an account",
                "Already have an account?",
                "Log in",
                "Log In",
                "Login",
            ],
            timeout=4,
        ):
            self._wait(2)
            if self._wait_for_login_form(device, timeout=5):
                return

        width, height = self._display_size(device)
        for y_ratio in (0.69, 0.73, 0.82):
            device.click(width // 2, int(height * y_ratio))
            self._wait(2)
            if self._wait_for_login_form(device, timeout=3):
                return

    def _click_saved_profile_entrypoint(self, device: Any) -> bool:
        text = self._hierarchy(device).lower()
        if "remove profiles" in text:
            return False
        if "profile photo" not in text:
            return False
        width, height = self._display_size(device)
        for y_ratio in (0.52, 0.58, 0.64):
            device.click(width // 2, int(height * y_ratio))
            self._wait(2)
            text = self._hierarchy(device).lower()
            if self._looks_authenticated(text) or any(marker in text for marker in CHALLENGE_MARKERS):
                return True
            if self._wait_for_login_form(device, timeout=1):
                return True
        for _ in range(2):
            device.swipe(width // 2, int(height * 0.82), width // 2, int(height * 0.36), 0.35)
            self._wait(1)
            text = self._hierarchy(device).lower()
            if self._looks_authenticated(text) or any(marker in text for marker in CHALLENGE_MARKERS):
                return True
            if self._wait_for_login_form(device, timeout=1):
                return True
        return True

    def _fill_login_form(self, device: Any, username: str, password: str) -> None:
        hierarchy = self._hierarchy(device).lower()
        password_only = "password" in hierarchy and "username" not in hierarchy and "email" not in hierarchy
        if password_only:
            if not self._try_set_edit_text(device, 0, password):
                width, height = self._display_size(device)
                device.click(width // 2, int(height * 0.62))
                self._send_keys(device, password)
            self._wait(1)
            self._hide_soft_keyboard(device)
            width, height = self._display_size(device)
            device.swipe(width // 2, int(height * 0.80), width // 2, int(height * 0.42), 0.25)
            self._wait(1)
            return
        if not self._try_set_edit_text(device, 0, username):
            width, height = self._display_size(device)
            device.click(width // 2, int(height * 0.45))
            self._send_keys(device, username)
        self._wait(1)
        if not self._try_set_edit_text(device, 1, password):
            width, height = self._display_size(device)
            device.click(width // 2, int(height * 0.64))
            self._send_keys(device, password)
        self._wait(1)
        self._hide_soft_keyboard(device)

    def _hide_soft_keyboard(self, device: Any) -> None:
        try:
            device.press("back")
        except Exception:
            pass
        self._wait(1)
        text = self._hierarchy(device).lower()
        if "clear text" in text or "switch input method" in text:
            try:
                device.shell("input keyevent 4")
            except Exception:
                pass
            self._wait(1)
        text = self._hierarchy(device).lower()
        if "clear text" in text or "switch input method" in text:
            try:
                device.shell("input tap 95 780")
            except Exception:
                pass
            self._wait(1)

    def _open_latest_post(
        self,
        device: Any,
        context: WorkerContext,
        payload: PlatformTaskPayload,
        artifacts: AndroidArtifacts,
    ) -> bool:
        self._dismiss_popups(device)
        self._exit_story_viewer_if_visible(device)
        self._capture(device, context, payload, "before-latest-post", artifacts)
        if self._click_media_grid_item(device, timeout=5):
            self._wait(3)
            self._capture(device, context, payload, "latest-post-opened", artifacts)
            return not self._story_viewer_visible_text(self._hierarchy(device).lower())

        width, height = self._display_size(device)
        for attempt in range(3):
            self._exit_story_viewer_if_visible(device)
            device.swipe(width // 2, int(height * 0.82), width // 2, int(height * 0.30), 0.35)
            self._wait(1)
            self._capture(device, context, payload, f"profile-grid-scroll-{attempt + 1}", artifacts)
            if self._click_media_grid_item(device, timeout=2):
                self._wait(3)
                self._capture(device, context, payload, "latest-post-opened-after-scroll", artifacts)
                return not self._story_viewer_visible_text(self._hierarchy(device).lower())
            if self._open_visible_grid_thumbnail(device):
                self._wait(3)
                self._capture(device, context, payload, "latest-post-coordinate-opened-after-scroll", artifacts)
                text = self._hierarchy(device).lower()
                return self._screen_has_any(device, ("like", "comment", "share", "send")) and not (
                    self._story_viewer_visible_text(text)
                )

        device.click(int(width * 0.17), int(height * 0.82))
        self._wait(3)
        self._capture(device, context, payload, "latest-post-coordinate-opened", artifacts)
        text = self._hierarchy(device).lower()
        has_post_controls = self._screen_has_any(device, ("like", "comment", "share", "send"))
        return has_post_controls and not self._story_viewer_visible_text(
            text,
        )

    def _open_visible_grid_thumbnail(self, device: Any) -> bool:
        hierarchy = self._hierarchy(device).lower()
        if "discover people" in hierarchy and "clips_grid_view" not in hierarchy and "profile_grid" not in hierarchy:
            return False
        width, height = self._display_size(device)
        for y_ratio in (0.82, 0.78, 0.74):
            device.click(int(width * 0.17), int(height * y_ratio))
            self._wait(1)
            if self._screen_has_any(device, ("like", "comment", "share", "send")):
                return True
            try:
                device.press("back")
            except Exception:
                pass
            self._wait(1)
        return False

    def _open_own_profile_tab(
        self,
        device: Any,
        context: WorkerContext,
        payload: PlatformTaskPayload,
        artifacts: AndroidArtifacts,
    ) -> None:
        self._dismiss_popups(device)
        self._exit_story_viewer_if_visible(device)
        if not self._click_any_description(device, ["Profile", "Your profile"], timeout=5):
            width, height = self._display_size(device)
            device.click(int(width * 0.90), int(height * 0.78))
        self._wait(4)
        self._exit_story_viewer_if_visible(device)
        self._capture(device, context, payload, "own-profile-opened", artifacts)

    def _exit_story_viewer_if_visible(self, device: Any) -> None:
        for _ in range(3):
            if not self._story_viewer_visible_text(self._hierarchy(device).lower()):
                return
            try:
                device.press("back")
            except Exception:
                width, height = self._display_size(device)
                device.click(int(width * 0.08), int(height * 0.08))
            self._wait(1)

    def _open_share_sheet(
        self,
        device: Any,
        context: WorkerContext,
        payload: PlatformTaskPayload,
        artifacts: AndroidArtifacts,
    ) -> bool:
        width, height = self._display_size(device)
        self._tap(device, int(width * 0.30), int(height * 0.80))
        self._wait(2)
        self._capture(device, context, payload, "share-sheet-opened-coordinate", artifacts)
        if self._screen_has_any(device, ("add to story", "copy link", "share to", "send to")):
            return True
        try:
            device.press("back")
        except Exception:
            pass
        self._wait(1)

        share_descriptions = ["Send post", "Share post", "Share", "Send"]
        if self._click_any_description(device, share_descriptions, timeout=5):
            self._wait(2)
            self._capture(device, context, payload, "share-sheet-opened", artifacts)
            return True
        if self._click_any_text(device, ["Share", "Send"], timeout=3):
            self._wait(2)
            self._capture(device, context, payload, "share-sheet-opened-text", artifacts)
            return True

        for attempt in range(3):
            device.swipe(width // 2, int(height * 0.78), width // 2, int(height * 0.33), 0.25)
            self._wait(1)
            self._capture(device, context, payload, f"share-actions-visible-{attempt + 1}", artifacts)
            if self._click_any_description(device, share_descriptions, timeout=3) or self._click_any_text(
                device, ["Share", "Send"], timeout=2
            ):
                self._wait(2)
                self._capture(device, context, payload, "share-sheet-opened-after-scroll", artifacts)
                return True

        device.click(int(width * 0.62), int(height * 0.45))
        self._wait(2)
        self._capture(device, context, payload, "share-coordinate-action-row", artifacts)
        if self._screen_has_any(device, ("add to story", "copy link", "share to", "send to")):
            return True

        for y_ratio in (0.61, 0.67, 0.72):
            device.click(int(width * 0.33), int(height * y_ratio))
            self._wait(2)
            self._capture(device, context, payload, f"share-coordinate-{int(y_ratio * 100)}", artifacts)
            if self._screen_has_any(device, ("add to story", "copy link", "share to", "send to")):
                return True
        return False

    def _click_add_to_story(
        self,
        device: Any,
        context: WorkerContext,
        payload: PlatformTaskPayload,
        artifacts: AndroidArtifacts,
    ) -> bool:
        width, height = self._display_size(device)
        for x_ratio, y_ratio in ((0.13, 0.81), (0.12, 0.80)):
            self._tap(device, int(width * x_ratio), int(height * y_ratio))
            if self._wait_for_story_editor_after_add_click(
                device,
                context,
                payload,
                artifacts,
                f"story-editor-opened-coordinate-{int(x_ratio * 100)}-{int(y_ratio * 100)}",
            ):
                return True
            self._dismiss_story_prompts(device)
            if not self._screen_has_any(device, ("add to story", "copy link", "share to", "send to")):
                try:
                    device.press("back")
                except Exception:
                    pass
                self._wait(1)

        if self._click_add_to_story_marker(device):
            return self._wait_for_story_editor_after_add_click(
                device,
                context,
                payload,
                artifacts,
                "story-editor-opened",
            )

        share_row_y = int(height * 0.61)
        sweeps = (
            ("forward", int(width * 0.86), int(width * 0.14), 4),
            ("backward", int(width * 0.14), int(width * 0.86), 8),
        )
        for direction, start_x, end_x, attempts in sweeps:
            for attempt in range(attempts):
                device.swipe(start_x, share_row_y, end_x, share_row_y, 0.25)
                self._wait(1)
                self._capture(device, context, payload, f"add-to-story-scan-{direction}-{attempt + 1}", artifacts)
                if self._click_add_to_story_marker(device):
                    return self._wait_for_story_editor_after_add_click(
                        device,
                        context,
                        payload,
                        artifacts,
                        f"story-editor-opened-after-{direction}-swipe",
                    )
        self._capture(device, context, payload, "add-to-story-not-found", artifacts)
        return False

    def _click_add_to_story_marker(self, device: Any) -> bool:
        for marker in ADD_TO_STORY_MARKERS:
            if self._click_exact_share_button_from_hierarchy(device, marker):
                return True
            try:
                if device(resourceId=f"{INSTAGRAM_ANDROID_PACKAGE}:id/button", description=marker).click_exists(
                    timeout=0.5
                ):
                    return True
            except Exception:
                pass
            if self._click_any_description(device, [marker], timeout=1) or self._click_any_text(
                device, [marker], timeout=1
            ):
                return True
        return False

    def _click_exact_share_button_from_hierarchy(self, device: Any, marker: str) -> bool:
        hierarchy = self._hierarchy(device)
        try:
            root = ET.fromstring(hierarchy)
        except ET.ParseError:
            return False

        candidates: list[tuple[int, tuple[int, int, int, int]]] = []
        for node in root.iter("node"):
            if node.attrib.get("content-desc") != marker:
                continue
            score = 0
            if node.attrib.get("resource-id") == f"{INSTAGRAM_ANDROID_PACKAGE}:id/button":
                score += 3
            if node.attrib.get("clickable") == "true":
                score += 2
            if node.attrib.get("class") == "android.widget.ImageView":
                score += 1
            if score <= 0:
                continue
            bounds = node.attrib.get("bounds", "")
            bounds_match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if not bounds_match:
                continue
            left, top, right, bottom = (int(value) for value in bounds_match.groups())
            candidates.append((score, (left, top, right, bottom)))

        if not candidates:
            return False
        _, (left, top, right, bottom) = max(candidates, key=lambda candidate: candidate[0])
        self._tap(device, (left + right) // 2, (top + bottom) // 2)
        return True

    def _wait_for_story_editor_after_add_click(
        self,
        device: Any,
        context: WorkerContext,
        payload: PlatformTaskPayload,
        artifacts: AndroidArtifacts,
        capture_name: str,
    ) -> bool:
        for _ in range(15):
            self._wait(1)
            if not self._is_instagram_foreground(device):
                self._capture(device, context, payload, f"{capture_name}-app-not-foreground", artifacts)
                return False
            self._dismiss_story_prompts(device)
            if self._story_editor_visible(device):
                self._capture(device, context, payload, capture_name, artifacts)
                return True
        self._capture(device, context, payload, f"{capture_name}-not-opened", artifacts)
        return False

    def _open_direct_media_story_editor(
        self,
        device: Any,
        settings: Settings,
        serial: str,
        media_path: str,
        context: WorkerContext,
        payload: PlatformTaskPayload,
        artifacts: AndroidArtifacts,
    ) -> bool:
        device_path = self._push_media_to_device(settings, serial, media_path)
        self._register_media_in_store(settings, serial, device_path, media_path)
        device_uri = f"file://{device_path}"
        content_uri = self._media_store_content_uri(settings, serial, device_path, media_path)
        mime_type = self._media_mime_type(media_path)
        self._adb(settings, ["-s", serial, "shell", "am", "force-stop", INSTAGRAM_ANDROID_PACKAGE], timeout=20)
        self._wait(1)
        attempts = [
            [
                "-s",
                serial,
                "shell",
                "am",
                "start",
                "-n",
                INSTAGRAM_CUSTOM_STORY_SHARE_ACTIVITY,
                "-a",
                "com.instagram.share.ADD_TO_STORY",
                "-d",
                content_uri or device_uri,
                "-t",
                mime_type,
                "--es",
                "source_application",
                "media_automata",
                "--grant-read-uri-permission",
            ],
            [
                "-s",
                serial,
                "shell",
                "am",
                "start",
                "-n",
                INSTAGRAM_CUSTOM_STORY_SHARE_ACTIVITY,
                "-a",
                "com.instagram.share.ADD_TO_STORY",
                "-d",
                device_uri,
                "-t",
                mime_type,
                "--es",
                "source_application",
                "media_automata",
                "--grant-read-uri-permission",
            ],
            [
                "-s",
                serial,
                "shell",
                "am",
                "start",
                "-n",
                INSTAGRAM_CUSTOM_STORY_SHARE_ACTIVITY,
                "-a",
                "com.instagram.share.ADD_TO_STORY",
                "-t",
                mime_type,
                "--eu",
                "interactive_asset_uri",
                content_uri or device_uri,
                "--grant-read-uri-permission",
            ],
            [
                "-s",
                serial,
                "shell",
                "am",
                "start",
                "-n",
                INSTAGRAM_STORY_SHARE_ACTIVITY,
                "-a",
                "android.intent.action.SEND",
                "-t",
                mime_type,
                "--eu",
                "android.intent.extra.STREAM",
                content_uri or device_uri,
                "--grant-read-uri-permission",
            ],
        ]

        for index, args in enumerate(attempts, start=1):
            completed = self._adb(settings, args, timeout=25)
            artifacts.adb_logs.append(completed.stdout.strip() or completed.stderr.strip())
            self._wait(6)
            self._capture(device, context, payload, f"direct-story-intent-{index}", artifacts)
            if self._discard_prompt_visible(device):
                artifacts.adb_logs.append(
                    f"direct-story-intent-{index}: Instagram opened a discard-draft modal; "
                    "restarting into gallery fallback."
                )
                return self._open_direct_media_story_editor_from_gallery(
                    device,
                    settings,
                    serial,
                    context,
                    payload,
                    artifacts,
                )
            self._dismiss_story_prompts(device)
            if self._advance_direct_story_picker(device):
                self._wait(5)
                self._dismiss_story_prompts(device)
                self._capture(device, context, payload, f"direct-story-picker-advanced-{index}", artifacts)
                if self._story_editor_visible(device):
                    return True
            if self._story_editor_visible(device):
                return True
            if self._select_story_account_if_prompted(device):
                self._wait(6)
                self._dismiss_story_prompts(device)
                self._capture(device, context, payload, f"direct-story-account-selected-{index}", artifacts)
                if self._story_editor_visible(device):
                    return True
            story_labels = ["Story", "Stories", "Your story"]
            if self._click_any_text(device, story_labels, timeout=4) or self._click_any_description(
                device, story_labels, timeout=4
            ):
                self._wait(5)
                self._dismiss_story_prompts(device)
                self._capture(device, context, payload, f"direct-story-selected-{index}", artifacts)
                if self._story_editor_visible(device):
                    return True
        return self._open_direct_media_story_editor_from_gallery(
            device,
            settings,
            serial,
            context,
            payload,
            artifacts,
        )

    def _open_direct_media_story_editor_from_gallery(
        self,
        device: Any,
        settings: Settings,
        serial: str,
        context: WorkerContext,
        payload: PlatformTaskPayload,
        artifacts: AndroidArtifacts,
    ) -> bool:
        self._adb(settings, ["-s", serial, "shell", "am", "force-stop", INSTAGRAM_ANDROID_PACKAGE], timeout=20)
        self._wait(1)
        self._start_instagram(device, settings, serial)
        self._dismiss_popups(device)
        self._capture(device, context, payload, "direct-story-gallery-home", artifacts)
        width, height = self._display_size(device)
        if not (
            self._click_any_resource_id(device, [f"{INSTAGRAM_ANDROID_PACKAGE}:id/creation_tab"], timeout=4)
            or self._click_any_description(device, ["Create"], timeout=4)
        ):
            device.click(width // 2, int(height * 0.96))
        self._wait(4)
        self._dismiss_story_prompts(device)
        self._capture(device, context, payload, "direct-story-create-tab", artifacts)

        if not self._story_camera_visible(device):
            if not (
                self._click_any_resource_id(device, [f"{INSTAGRAM_ANDROID_PACKAGE}:id/cam_dest_story"], timeout=4)
                or self._click_any_text(device, ["STORY", "Story"], timeout=4)
                or self._click_any_description(device, ["STORY", "Story"], timeout=4)
            ):
                device.click(int(width * 0.66), int(height * 0.95))
            self._wait(4)
            self._dismiss_story_prompts(device)
        self._capture(device, context, payload, "direct-story-camera", artifacts)

        if not (
            self._click_any_resource_id(
                device,
                [f"{INSTAGRAM_ANDROID_PACKAGE}:id/gallery_preview_button"],
                timeout=3,
            )
            or self._click_any_description(device, ["Gallery"], timeout=3)
        ):
            device.click(int(width * 0.20), int(height * 0.72))
        self._wait(4)
        self._dismiss_story_prompts(device)
        self._capture(device, context, payload, "direct-story-gallery-picker", artifacts)

        if not self._select_first_gallery_media(device):
            device.click(int(width * 0.22), int(height * 0.72))
        self._wait(3)
        self._dismiss_story_prompts(device)
        self._capture(device, context, payload, "direct-story-gallery-selected", artifacts)
        if self._advance_direct_story_picker(device):
            self._wait(5)
            self._dismiss_story_prompts(device)
            self._capture(device, context, payload, "direct-story-gallery-advanced", artifacts)
        elif self._click_any_text(device, ["Next"], timeout=3) or self._click_any_description(
            device,
            ["Next"],
            timeout=3,
        ):
            self._wait(5)
            self._dismiss_story_prompts(device)
            self._capture(device, context, payload, "direct-story-gallery-next", artifacts)
        return self._story_editor_visible(device)

    def _select_first_gallery_media(self, device: Any) -> bool:
        resource_ids = [
            f"{INSTAGRAM_ANDROID_PACKAGE}:id/gallery_grid_item_thumbnail",
            f"{INSTAGRAM_ANDROID_PACKAGE}:id/gallery_grid_item",
            f"{INSTAGRAM_ANDROID_PACKAGE}:id/media_thumbnail",
        ]
        if self._click_any_resource_id(device, resource_ids, timeout=3):
            return True
        descriptions = ["Photo thumbnail", "Video thumbnail", "Photo", "Video"]
        return self._click_any_description(device, descriptions, timeout=2)

    def _select_story_account_if_prompted(self, device: Any) -> bool:
        text = self._hierarchy(device).lower()
        if "create new account" not in text and "profile photo" not in text:
            return False
        width, height = self._display_size(device)
        device.click(width // 2, int(height * 0.60))
        return True

    def _advance_direct_story_picker(self, device: Any) -> bool:
        text = self._hierarchy(device).lower()
        if "cam_dest_story" not in text and "story" not in text:
            return False
        if "next" not in text and "next_button_textview" not in text:
            return False
        clicked_story = self._click_any_resource_id(
            device,
            [f"{INSTAGRAM_ANDROID_PACKAGE}:id/cam_dest_story"],
            timeout=2,
        ) or self._click_any_text(device, ["STORY", "Story"], timeout=2)
        if clicked_story:
            self._wait(1)
        return self._click_any_resource_id(
            device,
            [f"{INSTAGRAM_ANDROID_PACKAGE}:id/next_button_textview"],
            timeout=3,
        ) or self._click_any_text(device, ["Next"], timeout=3)

    def _apply_story_editor_actions(
        self,
        device: Any,
        settings: Settings,
        serial: str,
        context: WorkerContext,
        payload: PlatformTaskPayload,
        artifacts: AndroidArtifacts,
    ) -> None:
        actions = self._story_editor_actions(payload)
        if not actions:
            return
        self._dismiss_story_prompts(device)
        self._capture(device, context, payload, "story-editor-before-actions", artifacts)
        for index, action in enumerate(actions, start=1):
            action_type = str(action.get("type") or "").strip().lower()
            if action_type == "resize":
                self._resize_story_object(device, settings, serial, str(action.get("scale") or "large"))
            elif action_type == "move":
                self._move_story_object(device, str(action.get("position") or "center"))
            elif action_type == "tap_card_variant":
                self._tap_story_card_variant(device)
            elif action_type == "text":
                self._add_story_text(
                    device,
                    settings,
                    serial,
                    str(action.get("text") or ""),
                    position=str(action.get("position") or "center"),
                    font=str(action.get("font") or ""),
                    color=str(action.get("color") or ""),
                )
            elif action_type == "mention":
                username = str(action.get("username") or "").strip().lstrip("@")
                if username:
                    self._add_story_text(
                        device,
                        settings,
                        serial,
                        f"@{username}",
                        position=str(action.get("position") or "center"),
                    )
            elif action_type == "link":
                url = self._resolve_story_link(payload, action)
                if url:
                    self._add_story_link(device, settings, serial, url, label=str(action.get("label") or ""))
            elif action_type == "music":
                self._add_story_music(device, str(action.get("query") or ""))
            self._dismiss_story_prompts(device)
            action_name = self._safe_action_name(action_type)
            self._capture(device, context, payload, f"story-action-{index}-{action_name}", artifacts)

    def _story_editor_actions(self, payload: PlatformTaskPayload) -> list[dict[str, Any]]:
        raw_actions = payload.content.extra.get(INSTAGRAM_STORY_EDITOR_ACTIONS_KEY) or []
        if not isinstance(raw_actions, list):
            return []
        return self._ordered_story_editor_actions([action for action in raw_actions if isinstance(action, dict)])

    def _pre_render_direct_story_text_overlays(
        self,
        media_path: str,
        payload: PlatformTaskPayload,
        context: WorkerContext,
        artifacts: AndroidArtifacts,
    ) -> tuple[str, PlatformTaskPayload]:
        actions = self._story_editor_actions(payload)
        text_actions = [action for action in actions if str(action.get("type") or "").strip().lower() == "text"]
        if not text_actions or not self._media_mime_type(media_path).startswith("image/"):
            return media_path, payload

        try:
            with Image.open(media_path) as source_image:
                image = ImageOps.exif_transpose(source_image).convert("RGB")
        except (OSError, UnidentifiedImageError):
            return media_path, payload

        story_size = (1080, 1920)
        background = ImageOps.fit(image, story_size, method=Image.Resampling.LANCZOS)
        background = background.filter(ImageFilter.GaussianBlur(32))
        dim = Image.new("RGB", story_size, (0, 0, 0))
        canvas = Image.blend(background, dim, 0.28)

        foreground = image.copy()
        foreground.thumbnail(story_size, Image.Resampling.LANCZOS)
        paste_x = (story_size[0] - foreground.width) // 2
        paste_y = (story_size[1] - foreground.height) // 2
        canvas.paste(foreground, (paste_x, paste_y))

        draw = ImageDraw.Draw(canvas, "RGBA")
        for action in text_actions:
            self._draw_story_text_overlay(
                draw,
                str(action.get("text") or ""),
                position=str(action.get("position") or "center"),
                color=str(action.get("color") or "white"),
                story_size=story_size,
            )

        rendered_path = context.artifact_root / f"instagram-native-{payload.job_id}-pre-rendered-story.jpg"
        canvas.save(rendered_path, quality=94)
        artifacts.adb_logs.append(f"pre-rendered direct Story text overlays into {rendered_path}")

        remaining_actions = [
            action
            for action in actions
            if str(action.get("type") or "").strip().lower() not in {"text", "mention"}
            and not (
                str(action.get("type") or "").strip().lower() in {"resize", "move"}
                and str(action.get("target") or "").strip().lower() in {"", "media"}
            )
        ]
        content = payload.content.model_copy(
            update={
                "extra": {
                    **payload.content.extra,
                    INSTAGRAM_STORY_EDITOR_ACTIONS_KEY: remaining_actions,
                }
            }
        )
        return str(rendered_path), payload.model_copy(update={"content": content})

    def _draw_story_text_overlay(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        *,
        position: str,
        color: str,
        story_size: tuple[int, int],
    ) -> None:
        clean_text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if not clean_text:
            return
        font = self._story_font(58)
        wrapped_lines: list[str] = []
        for line in clean_text.splitlines():
            wrapped_lines.extend(textwrap.wrap(line, width=28) or [line])
        rendered_text = "\n".join(wrapped_lines)
        bbox = draw.multiline_textbbox((0, 0), rendered_text, font=font, spacing=12, align="center")
        text_width = int(bbox[2] - bbox[0])
        text_height = int(bbox[3] - bbox[1])
        x, y = self._story_render_position(story_size, position, text_width, text_height)
        padding_x = 34
        padding_y = 24
        fill = (255, 255, 255, 245) if color.lower() == "black" else (0, 0, 0, 218)
        text_fill = (0, 0, 0, 255) if color.lower() == "black" else (255, 255, 255, 255)
        draw.rounded_rectangle(
            (x - padding_x, y - padding_y, x + text_width + padding_x, y + text_height + padding_y),
            radius=26,
            fill=fill,
        )
        draw.multiline_text((x, y), rendered_text, font=font, fill=text_fill, spacing=12, align="center")

    @staticmethod
    def _story_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        for path in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        ):
            if Path(path).exists():
                return ImageFont.truetype(path, size=size)
        return ImageFont.load_default()

    @staticmethod
    def _story_render_position(
        story_size: tuple[int, int],
        position: str,
        text_width: int,
        text_height: int,
    ) -> tuple[int, int]:
        width, height = story_size
        normalized = position.lower()
        y_ratio = 0.20 if "top" in normalized else 0.70 if "bottom" in normalized else 0.48
        x_ratio = 0.25 if "left" in normalized else 0.75 if "right" in normalized else 0.50
        x = int(width * x_ratio - text_width / 2)
        y = int(height * y_ratio - text_height / 2)
        return max(64, min(x, width - text_width - 64)), max(120, min(y, height - text_height - 220))

    @staticmethod
    def _ordered_story_editor_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        order = {
            "resize": 0,
            "move": 1,
            "tap_card_variant": 2,
            "music": 3,
            "link": 4,
            "text": 5,
            "mention": 6,
        }
        ordered = sorted(
            actions,
            key=lambda action: (
                order.get(str(action.get("type") or "").strip().lower(), 50),
                actions.index(action),
            ),
        )
        return InstagramNativeWorker._coalesce_text_overlays(ordered)

    @staticmethod
    def _coalesce_text_overlays(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        text_lines: list[str] = []
        text_action: dict[str, Any] | None = None
        non_text_actions: list[dict[str, Any]] = []
        for action in actions:
            action_type = str(action.get("type") or "").strip().lower()
            if action_type == "text":
                value = str(action.get("text") or "").strip()
                if value:
                    text_lines.append(value)
                if text_action is None:
                    text_action = dict(action)
                continue
            if action_type == "mention":
                username = str(action.get("username") or "").strip().lstrip("@")
                if username:
                    text_lines.append(f"@{username}")
                if text_action is None:
                    text_action = {
                        "type": "text",
                        "position": action.get("position") or "center",
                    }
                continue
            non_text_actions.append(action)
        if text_lines and text_action is not None:
            text_action["type"] = "text"
            text_action["text"] = "\n".join(text_lines)
            non_text_actions.append(text_action)
        return non_text_actions

    def _resize_story_object(self, device: Any, settings: Settings, serial: str, scale: str) -> None:
        width, height = self._display_size(device)
        center_x = width // 2
        center_y = int(height * 0.44)
        if scale in {"small", "smaller", "fit"}:
            self._pinch(settings, serial, center_x, center_y, direction="in")
            return
        repeats = 2 if scale in {"full", "fullscreen"} else 1
        for _ in range(repeats):
            self._pinch(settings, serial, center_x, center_y, direction="out")

    def _move_story_object(self, device: Any, position: str) -> None:
        width, height = self._display_size(device)
        target_x, target_y = self._story_position_coordinates(width, height, position)
        device.drag(width // 2, int(height * 0.44), target_x, target_y, duration=0.35)
        self._wait(1)

    def _tap_story_card_variant(self, device: Any) -> None:
        width, height = self._display_size(device)
        device.click(width // 2, int(height * 0.44))
        self._wait(1)

    def _add_story_text(
        self,
        device: Any,
        settings: Settings,
        serial: str,
        text: str,
        *,
        position: str = "center",
        font: str = "",
        color: str = "",
    ) -> None:
        if not text:
            return
        width, height = self._display_size(device)
        if not self._click_any_resource_id(device, ["com.instagram.android:id/add_text_button"], timeout=3):
            device.click(int(width * 0.50), int(height * 0.06))
        self._wait(2)
        self._send_keys(device, text)
        self._select_story_font(device, font)
        self._select_story_color(device, color)
        if not self._click_done(device, timeout=3):
            device.click(int(width * 0.91), int(height * 0.04))
            self._wait(1)
        if self._story_text_editor_visible(device):
            device.click(int(width * 0.91), int(height * 0.04))
        self._confirm_story_text_done(device, settings, serial)
        self._wait(1)
        if not self._story_text_editor_visible(device):
            self._move_story_object(device, position)
            self._deselect_story_object(device)

    def _confirm_story_text_done(self, device: Any, settings: Settings, serial: str) -> None:
        if not self._story_text_editor_visible(device):
            return
        width, height = self._display_size(device)
        for y_ratio in (0.04, 0.05, 0.08):
            if not self._story_text_editor_visible(device):
                return
            self._adb(
                settings,
                ["-s", serial, "shell", "input", "tap", str(int(width * 0.91)), str(int(height * y_ratio))],
                timeout=10,
            )
            self._wait(0.8)
        self._hide_soft_keyboard(device)
        for y_ratio in (0.04, 0.05, 0.08):
            if not self._story_text_editor_visible(device):
                return
            self._adb(
                settings,
                ["-s", serial, "shell", "input", "tap", str(int(width * 0.91)), str(int(height * y_ratio))],
                timeout=10,
            )
            self._wait(1)

    def _deselect_story_object(self, device: Any) -> None:
        width, height = self._display_size(device)
        self._tap(device, int(width * 0.08), int(height * 0.50))
        self._wait(0.4)

    def _add_story_link(self, device: Any, settings: Settings, serial: str, url: str, *, label: str = "") -> None:
        width, height = self._display_size(device)
        if not self._open_story_sticker_tray(device):
            return
        self._tap(device, int(width * 0.76), int(height * 0.68))
        self._wait(2)
        if not self._link_editor_visible(device) and not (
            self._click_any_text(device, ["Link", "LINK"], timeout=4)
            or self._click_any_description(device, ["Link"], timeout=4)
        ):
            self._try_set_edit_text(device, 0, "Link")
            self._wait(1)
            if not self._click_any_text(device, ["Link", "LINK"], timeout=4):
                device.click(width // 2, int(height * 0.28))
        self._wait(2)
        for _ in range(2):
            self._tap(device, int(width * 0.40), int(height * 0.16))
            self._wait(0.5)
            self._send_keys(device, url)
            self._wait(1)
            if self._link_editor_done_enabled(device):
                break
        _ = label
        self._commit_link_editor_input(device, settings, serial)
        self._tap_link_editor_done(device, settings, serial)
        self._confirm_link_editor_done(device, settings, serial)
        self._wait(2)

    def _confirm_link_editor_done(self, device: Any, settings: Settings, serial: str) -> None:
        if not self._link_editor_visible(device):
            return
        self._tap_link_editor_done(device, settings, serial)
        if not self._link_editor_visible(device):
            return
        self._hide_soft_keyboard(device)
        for _ in range(8):
            if not self._link_editor_visible(device):
                return
            self._tap_link_editor_done(device, settings, serial)
            self._wait(1)

    def _tap_link_editor_done(self, device: Any, settings: Settings, serial: str) -> None:
        width, height = self._display_size(device)
        self._adb(
            settings,
            ["-s", serial, "shell", "input", "tap", str(int(width * 0.91)), str(int(height * 0.075))],
            timeout=10,
        )
        self._wait(0.8)

    def _commit_link_editor_input(self, device: Any, settings: Settings, serial: str) -> None:
        width, height = self._display_size(device)
        self._adb(
            settings,
            ["-s", serial, "shell", "input", "tap", str(int(width * 0.92)), str(int(height * 0.89))],
            timeout=10,
        )
        self._wait(1)
        if self._link_editor_visible(device) and not self._link_editor_done_enabled(device):
            self._press_enter(device)
            self._wait(1)

    def _link_editor_visible(self, device: Any) -> bool:
        text = self._hierarchy(device).lower()
        return "add link" in text and (
            "customize sticker text" in text
            or "people who view your story" in text
            or "see preview" in text
        )

    def _link_editor_done_enabled(self, device: Any) -> bool:
        hierarchy = self._hierarchy(device)
        try:
            root = ET.fromstring(hierarchy)
        except ET.ParseError:
            return False
        _, height = self._display_size(device)
        for node in root.iter("node"):
            label = (node.attrib.get("text") or node.attrib.get("content-desc") or "").strip().lower()
            if label != "done":
                continue
            bounds = node.attrib.get("bounds", "")
            bounds_match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if not bounds_match:
                continue
            top = int(bounds_match.group(2))
            if top < int(height * 0.20) and node.attrib.get("enabled") == "true":
                return True
        return False

    def _add_story_music(self, device: Any, query: str) -> None:
        query = query.strip()
        use_suggested = self._is_suggested_music_query(query)
        width, height = self._display_size(device)
        if not self._click_any_resource_id(device, ["com.instagram.android:id/music_button"], timeout=3):
            if not self._open_story_sticker_tray(device):
                return
            if not (
                self._click_any_text(device, ["Music", "MUSIC"], timeout=4)
                or self._click_any_description(device, ["Music"], timeout=4)
            ):
                return
        self._wait(2)
        if not use_suggested and query:
            if not self._click_any_resource_id(device, ["com.instagram.android:id/row_search_edit_text"], timeout=2):
                device.click(width // 2, int(height * 0.08))
            self._wait(0.5)
            if not self._try_set_edit_text(device, 0, query):
                self._send_keys(device, query)
            self._wait(1)
            if query.lower() not in self._hierarchy(device).lower():
                device.click(width // 2, int(height * 0.08))
                self._send_keys(device, query)
            self._wait(3)
        else:
            self._wait(2)
        if not self._click_first_music_track(device):
            device.click(width // 2, int(height * 0.08))
            self._wait(1)
        if not self._click_first_music_track(device):
            device.click(width // 2, int(height * 0.34))
        self._wait(2)
        if self._click_music_select_button(device):
            self._wait(2)
            self._click_done(device, timeout=3)
        else:
            if not self._click_done(device, timeout=3):
                device.click(int(width * 0.90), int(height * 0.90))
        self._wait(2)

    @staticmethod
    def _is_suggested_music_query(query: str) -> bool:
        normalized = re.sub(r"[\s_-]+", " ", query.strip().lower())
        return not normalized or normalized in {
            "suggested",
            "recommended",
            "first suggested",
            "first suggestion",
            "first recommended",
            "first recommendation",
            "instagram suggested",
            "instagram recommended",
        }

    def _click_first_music_track(self, device: Any) -> bool:
        hierarchy = self._hierarchy(device)
        width, height = self._display_size(device)
        try:
            root = ET.fromstring(hierarchy)
        except ET.ParseError:
            root = None
        if root is not None:
            candidates: list[tuple[int, tuple[int, int, int, int]]] = []
            for node in root.iter("node"):
                resource_id = node.attrib.get("resource-id") or ""
                description = (node.attrib.get("content-desc") or "").strip().lower()
                if not (
                    resource_id.endswith(":id/track_container")
                    or resource_id == "com.instagram.android:id/track_container"
                    or description.startswith("select track ")
                ):
                    continue
                bounds = node.attrib.get("bounds", "")
                bounds_match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                if not bounds_match:
                    continue
                left, top, right, bottom = (int(value) for value in bounds_match.groups())
                if top < int(height * 0.12) or bottom > int(height * 0.94):
                    continue
                score = 1000 - top
                if description.startswith("select track "):
                    score += 200
                if node.attrib.get("clickable") == "true":
                    score += 50
                candidates.append((score, (left, top, right, bottom)))
            if candidates:
                _, (left, top, right, bottom) = max(candidates, key=lambda candidate: candidate[0])
                tap_x = width // 2 if right - left > int(width * 0.75) else (left + right) // 2
                self._tap(device, tap_x, (top + bottom) // 2)
                return True
        return False

    def _click_music_select_button(self, device: Any) -> bool:
        hierarchy = self._hierarchy(device)
        width, height = self._display_size(device)
        try:
            root = ET.fromstring(hierarchy)
        except ET.ParseError:
            root = None
        if root is not None:
            candidates: list[tuple[int, tuple[int, int, int, int]]] = []
            for node in root.iter("node"):
                resource_id = node.attrib.get("resource-id") or ""
                if not resource_id.endswith(":id/select_button_tap_target"):
                    continue
                bounds = node.attrib.get("bounds", "")
                bounds_match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                if not bounds_match:
                    continue
                left, top, right, bottom = (int(value) for value in bounds_match.groups())
                if top < int(height * 0.70):
                    continue
                score = 1
                if node.attrib.get("clickable") == "true":
                    score += 4
                candidates.append((score, (left, top, right, bottom)))
            if candidates:
                _, (left, top, right, bottom) = max(candidates, key=lambda candidate: candidate[0])
                self._tap(device, (left + right) // 2, (top + bottom) // 2)
                return True

        if "music_browser_container" in hierarchy.lower() or "audio_bar" in hierarchy.lower():
            self._tap(device, int(width * 0.91), int(height * 0.90))
            return True
        return False

    def _open_story_sticker_tray(self, device: Any) -> bool:
        width, height = self._display_size(device)
        if self._click_any_resource_id(
            device,
            ["com.instagram.android:id/asset_button", "com.instagram.android:id/asset_button_container"],
            timeout=3,
        ):
            self._wait(2)
            return True
        if self._click_any_description(device, ["Emojis and stickers", "Stickers"], timeout=2):
            self._wait(2)
            return True
        device.click(int(width * 0.60), int(height * 0.18))
        self._wait(2)
        return self._screen_has_any(device, ("link", "music", "mention", "sticker"))

    def _click_done(self, device: Any, *, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            clicked = self._click_any_resource_id(
                device,
                ["com.instagram.android:id/done_button"],
                timeout=0.4,
            )
            if not clicked:
                clicked = self._tap_first_text_or_description_bounds(device, ["Done"], timeout=0.4)
            if not clicked:
                clicked = self._click_any_description(device, ["Done"], timeout=0.3) or self._click_any_text(
                    device,
                    ["Done"],
                    timeout=0.3,
                )
            if clicked:
                self._wait(0.8)
                if not self._story_text_editor_visible(device):
                    return True
            self._wait(0.2)
        return False

    def _story_text_editor_visible(self, device: Any) -> bool:
        text = self._hierarchy(device).lower()
        return (
            "clear text" in text
            or "switch ime" in text
            or "switch input method" in text
            or "modern text style" in text
            or "classic text style" in text
            or "text_mention_picker" in text
            or "text_location_picker" in text
            or ("done" in text and "mention" in text)
        )

    def _select_story_font(self, device: Any, font: str) -> None:
        if not font:
            return
        width, height = self._display_size(device)
        font_order = ["classic", "modern", "neon", "typewriter", "strong"]
        taps = font_order.index(font) if font in font_order else 1
        for _ in range(max(0, taps)):
            device.click(width // 2, int(height * 0.10))
            self._wait(0.3)

    def _select_story_color(self, device: Any, color: str) -> None:
        if not color:
            return
        width, height = self._display_size(device)
        color_x = {
            "white": 0.18,
            "black": 0.28,
            "red": 0.40,
            "yellow": 0.52,
            "green": 0.64,
            "blue": 0.76,
            "purple": 0.88,
        }.get(color.lower())
        if color_x is None:
            return
        device.click(int(width * color_x), int(height * 0.93))
        self._wait(0.5)

    def _pinch(self, settings: Settings, serial: str, center_x: int, center_y: int, *, direction: str) -> None:
        delta = 95
        if direction == "out":
            swipes = [
                (center_x - 18, center_y - 18, center_x - delta, center_y - delta),
                (center_x + 18, center_y + 18, center_x + delta, center_y + delta),
            ]
        else:
            swipes = [
                (center_x - delta, center_y - delta, center_x - 18, center_y - 18),
                (center_x + delta, center_y + delta, center_x + 18, center_y + 18),
            ]
        processes = [
            subprocess.Popen(
                [
                    settings.adb_path,
                    "-s",
                    serial,
                    "shell",
                    "input",
                    "touchscreen",
                    "swipe",
                    str(x1),
                    str(y1),
                    str(x2),
                    str(y2),
                    "350",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for x1, y1, x2, y2 in swipes
        ]
        for process in processes:
            process.wait(timeout=5)
        self._wait(1)

    def _story_position_coordinates(self, width: int, height: int, position: str) -> tuple[int, int]:
        positions = {
            "top left": (0.28, 0.24),
            "top right": (0.72, 0.24),
            "bottom left": (0.28, 0.64),
            "bottom right": (0.72, 0.64),
            "top": (0.50, 0.24),
            "bottom": (0.50, 0.64),
            "left": (0.28, 0.44),
            "right": (0.72, 0.44),
            "center": (0.50, 0.44),
            "middle": (0.50, 0.44),
        }
        x_ratio, y_ratio = positions.get(position.lower(), positions["center"])
        return int(width * x_ratio), int(height * y_ratio)

    def _resolve_story_link(self, payload: PlatformTaskPayload, action: dict[str, Any]) -> str:
        url = str(action.get("url") or "").strip()
        if url == AUTO_FEED_POST_URL:
            return str(payload.content.extra.get("instagram_post_url") or "").strip()
        return url

    def _story_editor_visible(self, device: Any) -> bool:
        if not self._is_instagram_foreground(device):
            return False
        text = self._hierarchy(device).lower()
        if self._discard_prompt_visible_text(text):
            return False
        if self._story_viewer_visible_text(text):
            return False
        return self._story_composer_visible_text(text)

    def _discard_prompt_visible(self, device: Any) -> bool:
        return self._discard_prompt_visible_text(self._hierarchy(device).lower())

    def _discard_prompt_visible_text(self, text: str) -> bool:
        return "discard" in text and ("discard photo" in text or "discard edits" in text or "go back now" in text)

    def _story_composer_visible_text(self, text: str) -> bool:
        if self._story_viewer_visible_text(text):
            return False
        if any(
            marker in text
            for marker in (
                "add_text_button",
                "asset_button",
                "music_button",
                "post_capture",
                "quick_capture",
                "gallery_picker_view",
                "cam_dest_story",
                "next_button_textview",
            )
        ):
            return True
        return "your story" in text and "close friends" in text and self._story_share_to_control_visible_text(text)

    def _story_camera_visible(self, device: Any) -> bool:
        text = self._hierarchy(device).lower()
        return (
            f"{INSTAGRAM_ANDROID_PACKAGE}:id/gallery_preview_button" in text
            or 'content-desc="gallery"' in text
            or "camera_shutter_button" in text
            or "quick_capture_root_container" in text
        ) and "cam_dest_story" in text

    @staticmethod
    def _story_viewer_visible_text(text: str) -> bool:
        native_viewer = any(
            marker in text
            for marker in (
                "reel_viewer_root",
                "reel_viewer_header",
                "reel_viewer_progress_bar",
                "send message or reaction",
                "like story",
                "sponsored story",
            )
        )
        web_style_viewer = "say something" in text and (
            "highlight" in text or "mention" in text or "send" in text
        )
        return native_viewer or web_style_viewer

    def _push_media_to_device(self, settings: Settings, serial: str, media_path: str) -> str:
        source = Path(media_path)
        suffix = source.suffix or ".jpg"
        device_path = f"/sdcard/Download/media-automata-{int(time.time() * 1000)}{suffix}"
        completed = self._adb(settings, ["-s", serial, "push", str(source), device_path], timeout=60)
        if completed.returncode != 0:
            raise AndroidRuntimeError(
                f"Could not push Story media to Android device: {completed.stderr or completed.stdout}",
                ErrorCode.MEDIA_UPLOAD_FAILED,
            )
        self._adb(
            settings,
            [
                "-s",
                serial,
                "shell",
                "am",
                "broadcast",
                "-a",
                "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                "-d",
                f"file://{device_path}",
            ],
            timeout=20,
        )
        self._wait(2)
        return device_path

    def _register_media_in_store(self, settings: Settings, serial: str, device_path: str, media_path: str) -> None:
        mime_type = self._media_mime_type(media_path)
        table = "video" if mime_type.startswith("video/") else "images"
        normalized_path = device_path.replace("/sdcard/", "/storage/emulated/0/")
        display_name = Path(device_path).name
        self._adb(
            settings,
            [
                "-s",
                serial,
                "shell",
                "content",
                "insert",
                "--uri",
                f"content://media/external/{table}/media",
                "--bind",
                f"_data:s:{normalized_path}",
                "--bind",
                f"mime_type:s:{mime_type}",
                "--bind",
                f"_display_name:s:{display_name}",
            ],
            timeout=30,
        )
        self._wait(1)

    def _media_store_content_uri(
        self,
        settings: Settings,
        serial: str,
        device_path: str,
        media_path: str,
    ) -> str | None:
        table = "video" if self._media_mime_type(media_path).startswith("video/") else "images"
        completed = self._adb(
            settings,
            [
                "-s",
                serial,
                "shell",
                "content",
                "query",
                "--uri",
                f"content://media/external/{table}/media",
                "--projection",
                "_id:_data",
            ],
            timeout=30,
        )
        haystack = f"{completed.stdout}\n{completed.stderr}"
        normalized_path = device_path.replace("/sdcard/", "/storage/emulated/0/")
        for line in haystack.splitlines():
            if device_path not in line and normalized_path not in line:
                continue
            match = re.search(r"_id=(\d+)", line)
            if match:
                return f"content://media/external/{table}/media/{match.group(1)}"
        return None

    def _media_mime_type(self, media_path: str) -> str:
        mime_type, _ = mimetypes.guess_type(media_path)
        return mime_type or "image/jpeg"

    def _safe_action_name(self, action_type: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_.-]+", "-", action_type or "unknown").strip("-") or "unknown"

    def _publish_story(
        self,
        device: Any,
        context: WorkerContext,
        payload: PlatformTaskPayload,
        artifacts: AndroidArtifacts,
    ) -> bool:
        width, height = self._display_size(device)
        for step in range(8):
            if not self._is_instagram_foreground(device):
                self._capture(device, context, payload, f"story-publish-step-{step + 1}-app-not-foreground", artifacts)
                return False
            text = self._hierarchy(device).lower()
            if self._discard_prompt_visible_text(text):
                self._capture(device, context, payload, f"story-publish-step-{step + 1}-discard-dialog", artifacts)
                artifacts.adb_logs.append("story-publish: blocked by Instagram discard-draft dialog.")
                return False
            self._dismiss_story_prompts(device)
            text = self._hierarchy(device).lower()
            if "also share to" in text:
                if not (
                    self._click_any_text(device, ["Done"], timeout=3)
                    or self._click_any_description(device, ["Done"], timeout=3)
                ):
                    device.click(width // 2, int(height * 0.74))
                self._wait(2)
                self._capture(device, context, payload, f"story-publish-step-{step + 1}-also-share-complete", artifacts)
                return True
            elif "now people can" in text or "people can share" in text:
                if not self._click_any_text(device, ["OK"], timeout=3):
                    device.click(width // 2, int(height * 0.76))
            elif self._story_share_sheet_visible_text(text):
                if not self._click_story_final_share_button(device):
                    self._tap(device, width // 2, int(height * 0.88))
            elif self._story_composer_visible_text(text):
                if self._story_share_to_control_visible_text(text):
                    if not self._click_story_share_to_control(device):
                        self._tap(device, int(width * 0.91), int(height * 0.87))
                else:
                    if not self._click_story_publish_control(device):
                        self._tap(device, int(width * 0.23), int(height * 0.87))
                    self._wait(2)
                    text_after_publish_tap = self._hierarchy(device).lower()
                    if (
                        self._story_composer_visible_text(text_after_publish_tap)
                        and self._story_share_to_control_visible_text(text_after_publish_tap)
                        and not self._story_uploading_visible_text(text_after_publish_tap)
                        and not self._discard_prompt_visible_text(text_after_publish_tap)
                    ):
                        if not self._click_story_share_to_control(device):
                            self._tap(device, int(width * 0.91), int(height * 0.87))
            elif "your story" in text and "share" in text:
                if not (
                    self._click_any_text(device, ["Share"], timeout=3)
                    or self._click_any_description(device, ["Share"], timeout=3)
                ):
                    device.click(width // 2, int(height * 0.76))
            else:
                device.click(width // 2, int(height * 0.76))
            self._wait(3)
            self._capture(device, context, payload, f"story-publish-step-{step + 1}", artifacts)
            text_after_step = self._hierarchy(device).lower()
            if self._story_uploading_visible_text(text_after_step) or self._story_success_visible_text(
                text_after_step,
            ):
                break
            if "instagram home feed" in text_after_step and not self._story_composer_visible_text(text_after_step):
                break
        return self._wait_for_story_submission(device, context, payload, artifacts)

    def _click_story_publish_control(self, device: Any) -> bool:
        hierarchy = self._hierarchy(device)
        width, height = self._display_size(device)
        try:
            root = ET.fromstring(hierarchy)
        except ET.ParseError:
            root = None
        if root is not None:
            candidates: list[tuple[int, tuple[int, int, int, int]]] = []
            for node in root.iter("node"):
                label = (node.attrib.get("text") or node.attrib.get("content-desc") or "").strip().lower()
                if label != "your story":
                    continue
                bounds = node.attrib.get("bounds", "")
                bounds_match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                if not bounds_match:
                    continue
                left, top, right, bottom = (int(value) for value in bounds_match.groups())
                if top < int(height * 0.65):
                    continue
                score = 1
                if node.attrib.get("clickable") == "true":
                    score += 4
                if node.attrib.get("class") == "android.widget.Button":
                    score += 3
                if (node.attrib.get("content-desc") or "").strip().lower() == "your story":
                    score += 2
                if right <= width // 2:
                    score += 1
                candidates.append((score, (left, top, right, bottom)))
            if candidates:
                _, (left, top, right, bottom) = max(candidates, key=lambda candidate: candidate[0])
                self._tap(device, (left + right) // 2, (top + bottom) // 2)
                return True

        return self._click_any_description(device, ["Your story"], timeout=2) or self._click_any_text(
            device,
            ["Your story"],
            timeout=2,
        )

    def _click_story_share_to_control(self, device: Any) -> bool:
        hierarchy = self._hierarchy(device)
        width, height = self._display_size(device)
        try:
            root = ET.fromstring(hierarchy)
        except ET.ParseError:
            root = None
        if root is not None:
            candidates: list[tuple[int, tuple[int, int, int, int]]] = []
            for node in root.iter("node"):
                label = (node.attrib.get("text") or node.attrib.get("content-desc") or "").strip().lower()
                if label != "share to":
                    continue
                bounds = node.attrib.get("bounds", "")
                bounds_match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                if not bounds_match:
                    continue
                left, top, right, bottom = (int(value) for value in bounds_match.groups())
                if top < int(height * 0.65):
                    continue
                score = 1
                if node.attrib.get("clickable") == "true":
                    score += 4
                if node.attrib.get("class") == "android.widget.Button":
                    score += 3
                if right >= int(width * 0.75):
                    score += 2
                candidates.append((score, (left, top, right, bottom)))
            if candidates:
                _, (left, top, right, bottom) = max(candidates, key=lambda candidate: candidate[0])
                self._tap(device, (left + right) // 2, (top + bottom) // 2)
                return True

        return self._click_any_description(device, ["Share to"], timeout=2) or self._click_any_text(
            device,
            ["Share to"],
            timeout=2,
        )

    def _story_share_sheet_visible_text(self, text: str) -> bool:
        return "sharing options" in text and "your story" in text and 'text="share"' in text

    def _story_share_to_control_visible_text(self, text: str) -> bool:
        return (
            'content-desc="share to"' in text
            or 'text="share to"' in text
            or ("share to" in text and "your story" in text and "close friends" in text)
        )

    def _click_story_final_share_button(self, device: Any) -> bool:
        hierarchy = self._hierarchy(device)
        width, height = self._display_size(device)
        try:
            root = ET.fromstring(hierarchy)
        except ET.ParseError:
            root = None
        if root is not None:
            candidates: list[tuple[int, tuple[int, int, int, int]]] = []
            for node in root.iter("node"):
                label = (node.attrib.get("text") or node.attrib.get("content-desc") or "").strip().lower()
                if label != "share":
                    continue
                bounds = node.attrib.get("bounds", "")
                bounds_match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                if not bounds_match:
                    continue
                left, top, right, bottom = (int(value) for value in bounds_match.groups())
                if top < int(height * 0.70):
                    continue
                score = 1
                if node.attrib.get("clickable") == "true":
                    score += 4
                if right - left > int(width * 0.50):
                    score += 3
                candidates.append((score, (left, top, right, bottom)))
            if candidates:
                _, (left, top, right, bottom) = max(candidates, key=lambda candidate: candidate[0])
                self._tap(device, (left + right) // 2, (top + bottom) // 2)
                return True

        return self._click_any_text(device, ["Share"], timeout=2) or self._click_any_description(
            device,
            ["Share"],
            timeout=2,
        )

    def _wait_for_story_submission(
        self,
        device: Any,
        context: WorkerContext,
        payload: PlatformTaskPayload,
        artifacts: AndroidArtifacts,
    ) -> bool:
        submitted = False
        upload_started = False
        upload_clear_count = 0
        for _ in range(90):
            self._wait(1)
            if not self._is_instagram_foreground(device):
                self._capture(device, context, payload, "story-submit-app-not-foreground", artifacts)
                return False
            text = self._hierarchy(device).lower()
            if self._discard_prompt_visible_text(text):
                self._capture(device, context, payload, "story-submit-discard-dialog", artifacts)
                return False
            if "introducing your stories archive" in text or "stories archive" in text:
                self._dismiss_story_prompts(device)
                self._capture(device, context, payload, "story-submit-archive-prompt", artifacts)
                return True
            composer_visible = self._story_composer_visible_text(text)
            if any(marker in text for marker in ("couldn't share", "try again", "failed", "error")):
                self._capture(device, context, payload, "story-submit-error", artifacts)
                return False
            uploading_visible = self._story_uploading_visible_text(text)
            if uploading_visible:
                upload_started = True
                upload_clear_count = 0
                submitted = True
                continue
            if upload_started and not composer_visible:
                upload_clear_count += 1
                if upload_clear_count >= 3:
                    self._capture(device, context, payload, "story-submit-upload-complete", artifacts)
                    return True
            if self._story_success_visible_text(text):
                submitted = True
            if "your story" in text and not composer_visible and "close friends" not in text:
                submitted = True
            if submitted and "instagram home feed" in text and not composer_visible:
                self._capture(device, context, payload, "story-submit-home-complete", artifacts)
                return True
            if submitted and not any(
                marker in text
                for marker in (
                    "add to story",
                    "share to",
                    "discard edits",
                    "close friends",
                    "add_text_button",
                    "asset_button",
                    "music_button",
                    "post_capture",
                )
            ):
                self._capture(device, context, payload, "story-submit-complete", artifacts)
                return True
        self._capture(device, context, payload, "story-submit-timeout", artifacts)
        return submitted and not self._story_composer_visible_text(self._hierarchy(device).lower())

    def _story_uploading_visible_text(self, text: str) -> bool:
        return any(
            marker in text
            for marker in (
                "story uploading",
                "uploading story",
                "instagram notification: story uploading",
            )
        )

    def _story_success_visible_text(self, text: str) -> bool:
        success_markers = (
            'text="shared"',
            'text="sent"',
            'content-desc="shared"',
            'content-desc="sent"',
            'content-desc="story shared',
        )
        return any(marker in text for marker in success_markers)

    def _looks_authenticated(self, text: str) -> bool:
        if any(marker in text for marker in CHALLENGE_MARKERS):
            return False
        if any(marker in text for marker in LOGIN_MARKERS):
            return False
        marker_count = sum(1 for marker in HOME_MARKERS if marker in text)
        app_navigation_visible = any(
            marker in text for marker in ("search", "reels", "your story", "like", "comment", "share", "send")
        )
        password_field_visible = any(
            marker in text
            for marker in (
                'text="password"',
                'content-desc="password',
                'hint="password"',
            )
        )
        return (
            marker_count >= 2
            and app_navigation_visible
            and not password_field_visible
            and "join instagram" not in text
        )

    def _classify_native_auth_state(self, device: Any) -> str:
        if not self._is_instagram_foreground(device):
            return "app_not_foreground"
        text = self._hierarchy(device).lower()
        if any(marker in text for marker in CHALLENGE_MARKERS):
            return "challenge_required"
        if any(marker in text for marker in LOGIN_MARKERS):
            return "login_required"
        if self._story_composer_visible_text(text):
            return "authenticated"
        if self._looks_authenticated(text):
            return "authenticated"
        return "unknown"

    def _dismiss_popups(self, device: Any) -> None:
        popup_texts = (
            "Not now",
            "Not Now",
            "Skip",
            "Maybe later",
            "Cancel",
            "Try again",
            "TRY AGAIN",
            "TRY",
            "Allow",
            "While using the app",
            "Only this time",
            "OK",
        )
        for _ in range(4):
            hierarchy_text = self._hierarchy(device).lower()
            if "allow instagram to access" in hierarchy_text or "permissioncontroller" in self._current_package(device):
                self._allow_visible_android_permission_dialog(device)
                self._wait(1)
                continue
            if self._story_composer_visible_text(hierarchy_text) and not any(
                marker in hierarchy_text
                for marker in (
                    "try it",
                    "not now",
                    "also share to",
                    "people can share",
                    "now people can",
                )
            ):
                return
            has_popup_marker = any(text.lower() in hierarchy_text for text in popup_texts if len(text) > 2)
            has_ok_button = 'text="ok"' in hierarchy_text or 'content-desc="ok"' in hierarchy_text
            if not has_popup_marker and not has_ok_button:
                return
            clicked = False
            for text in popup_texts:
                clicked = (
                    self._click_any_text(device, [text], timeout=1)
                    or self._click_any_description(device, [text], timeout=1)
                    or clicked
                )
            if not clicked and "allow instagram to access" in hierarchy_text:
                width, height = self._display_size(device)
                device.swipe(width // 2, int(height * 0.76), width // 2, int(height * 0.36), 0.30)
                self._wait(1)
                clicked = self._click_any_text(device, ["ALLOW", "Allow"], timeout=2) or self._click_any_description(
                    device,
                    ["ALLOW", "Allow"],
                    timeout=2,
                )
                if not clicked:
                    device.click(width // 2, int(height * 0.54))
                    clicked = True
            if not clicked:
                return
            self._wait(1)

    def _allow_visible_android_permission_dialog(self, device: Any) -> None:
        width, height = self._display_size(device)
        device.swipe(width // 2, int(height * 0.76), width // 2, int(height * 0.36), 0.30)
        self._wait(1)
        device.click(width // 2, int(height * 0.54))

    def _dismiss_story_prompts(self, device: Any) -> None:
        width, height = self._display_size(device)
        text = self._hierarchy(device).lower()
        if "create a sticker" in text and "not now" in text:
            device.click(width // 2, int(height * 0.75))
            self._wait(1)
            return
        if "introducing your stories archive" in text or "stories archive" in text:
            if not self._click_any_text(device, ["OK"], timeout=2):
                device.click(width // 2, int(height * 0.68))
            self._wait(1)
            return
        self._dismiss_popups(device)
        text = self._hierarchy(device).lower()
        if "discard" in text:
            if self._click_any_text(device, ["Keep editing", "Cancel"], timeout=2) or self._click_any_description(
                device, ["Keep editing", "Cancel"],
                timeout=2,
            ):
                self._wait(1)
                return
            try:
                device.press("back")
            except Exception:
                device.click(width // 2, int(height * 0.60))
            self._wait(1)
            return
        text = self._hierarchy(device).lower()
        if "leave a comment" in text and "not now" in text:
            if not self._click_any_text(device, ["Not now", "Not Now"], timeout=2):
                device.click(width // 2, int(height * 0.91))
            self._wait(1)
            return
        if "try it" in text and "not now" in text:
            if not self._click_any_text(device, ["Not now", "Not Now"], timeout=2):
                device.click(width // 2, int(height * 0.91))
            self._wait(1)
        text = self._hierarchy(device).lower()
        if "now people can" in text or "people can share" in text:
            if not self._click_any_text(device, ["OK"], timeout=2):
                device.click(width // 2, int(height * 0.76))
            self._wait(1)

    def _submit_verification_code(
        self,
        device: Any,
        code: str,
        context: WorkerContext,
        payload: PlatformTaskPayload,
        artifacts: AndroidArtifacts,
    ) -> bool:
        width, height = self._display_size(device)
        for attempt in range(5):
            if self._try_set_edit_text(device, 0, code):
                self._capture(device, context, payload, f"code-filled-{attempt + 1}", artifacts)
                if self._click_verification_continue(device):
                    self._capture(device, context, payload, "code-submitted", artifacts)
                    return True
                device.click(width // 2, int(height * 0.82))
                self._wait(1)
                self._capture(device, context, payload, "code-submitted-coordinate", artifacts)
                return True

            if self._click_any_text(device, ["Enter code"], timeout=1) or self._click_any_description(
                device, ["Enter code"], timeout=1
            ):
                self._send_keys(device, code)
                self._capture(device, context, payload, f"code-keyed-{attempt + 1}", artifacts)
                if self._click_verification_continue(device):
                    self._capture(device, context, payload, "code-submitted", artifacts)
                    return True
                device.click(width // 2, int(height * 0.82))
                self._wait(1)
                self._capture(device, context, payload, "code-submitted-coordinate", artifacts)
                return True

            device.swipe(width // 2, int(height * 0.80), width // 2, int(height * 0.35), 0.25)
            self._wait(1)
            self._capture(device, context, payload, f"code-field-scroll-{attempt + 1}", artifacts)
        return False

    def _click_verification_continue(self, device: Any) -> bool:
        labels = ["Continue", "Next", "Confirm"]
        return self._click_any_text(device, labels, timeout=3) or self._click_any_description(device, labels, timeout=3)

    def _click_login_submit_button(self, device: Any, *, timeout: float) -> bool:
        labels = {"Log in", "Log In", "Login"}
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            hierarchy = self._hierarchy(device)
            try:
                root = ET.fromstring(hierarchy)
            except ET.ParseError:
                root = None
            if root is not None:
                candidates: list[tuple[int, tuple[int, int, int, int]]] = []
                for node in root.iter("node"):
                    text = node.attrib.get("text") or ""
                    description = node.attrib.get("content-desc") or ""
                    if text not in labels and description not in labels:
                        continue
                    if node.attrib.get("clickable") != "true":
                        continue
                    bounds = node.attrib.get("bounds", "")
                    bounds_match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                    if not bounds_match:
                        continue
                    left, top, right, bottom = (int(value) for value in bounds_match.groups())
                    width = right - left
                    height = bottom - top
                    if width < 80 or height < 35:
                        continue
                    score = 1
                    if node.attrib.get("class") == "android.widget.Button":
                        score += 4
                    if description in labels:
                        score += 2
                    candidates.append((score, (left, top, right, bottom)))
                if candidates:
                    _, (left, top, right, bottom) = max(candidates, key=lambda candidate: candidate[0])
                    device.click((left + right) // 2, (top + bottom) // 2)
                    return True

            for label in labels:
                try:
                    if device(className="android.widget.Button", description=label).click_exists(timeout=0.3):
                        return True
                except Exception:
                    pass
            if self._click_any_description(device, list(labels), timeout=0.5):
                return True
            self._wait(0.2)
        return False

    def _click_media_grid_item(self, device: Any, *, timeout: float) -> bool:
        selectors = [
            lambda: device(descriptionContains="Photo by"),
            lambda: device(descriptionContains="Video by"),
            lambda: device(descriptionContains="Carousel by"),
            lambda: device(descriptionContains="Post by"),
            lambda: device(descriptionContains="Reel by"),
        ]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for selector in selectors:
                try:
                    if selector().click_exists(timeout=0.5):
                        return True
                except Exception:
                    continue
            self._wait(0.5)
        return False

    def _click_any_text(self, device: Any, texts: list[str], *, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for text in texts:
                try:
                    if device(text=text).click_exists(timeout=0.3):
                        return True
                except Exception:
                    pass
                try:
                    if device(textContains=text).click_exists(timeout=0.3):
                        return True
                except Exception:
                    pass
            self._wait(0.2)
        return False

    def _click_any_description(self, device: Any, descriptions: list[str], *, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for description in descriptions:
                try:
                    if device(description=description).click_exists(timeout=0.3):
                        return True
                except Exception:
                    pass
                try:
                    if device(descriptionContains=description).click_exists(timeout=0.3):
                        return True
                except Exception:
                    pass
            self._wait(0.2)
        return False

    def _tap_first_text_or_description_bounds(self, device: Any, values: list[str], *, timeout: float) -> bool:
        normalized_values = {value.strip().lower() for value in values if value.strip()}
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            hierarchy = self._hierarchy(device)
            try:
                root = ET.fromstring(hierarchy)
            except ET.ParseError:
                root = None
            if root is not None:
                for node in root.iter("node"):
                    text = (node.attrib.get("text") or "").strip().lower()
                    description = (node.attrib.get("content-desc") or "").strip().lower()
                    if text not in normalized_values and description not in normalized_values:
                        continue
                    bounds = node.attrib.get("bounds", "")
                    bounds_match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                    if not bounds_match:
                        continue
                    left, top, right, bottom = (int(value) for value in bounds_match.groups())
                    self._tap(device, (left + right) // 2, (top + bottom) // 2)
                    return True
            self._wait(0.2)
        return False

    def _click_any_resource_id(self, device: Any, resource_ids: list[str], *, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for resource_id in resource_ids:
                try:
                    if device(resourceId=resource_id).click_exists(timeout=0.3):
                        return True
                except Exception:
                    pass
            self._wait(0.2)
        return False

    def _try_set_edit_text(self, device: Any, index: int, value: str) -> bool:
        result_queue: queue.Queue[bool] = queue.Queue(maxsize=1)

        def set_text() -> None:
            try:
                field = device(className="android.widget.EditText", instance=index)
                try:
                    if not field.exists(timeout=0.8):
                        result_queue.put(False)
                        return
                except TypeError:
                    if not field.exists:
                        result_queue.put(False)
                        return
                field.click()
                field.set_text(value)
                result_queue.put(True)
            except Exception:
                result_queue.put(False)

        thread = threading.Thread(target=set_text, daemon=True)
        thread.start()
        try:
            return result_queue.get(timeout=4)
        except queue.Empty:
            return False

    def _send_keys(self, device: Any, value: str) -> None:
        try:
            device.set_clipboard(value)
            device.shell(["input", "keyevent", "279"], timeout=10)
            return
        except Exception:
            pass
        try:
            response = device.shell(["input", "text", self._adb_input_text(value)], timeout=10)
            if getattr(response, "exit_code", getattr(response, "returncode", 0)) == 0:
                return
        except Exception:
            pass
        raise AndroidRuntimeError("Could not type into Instagram Android text field.", ErrorCode.UNKNOWN_UI_STATE)

    def _adb_input_text(self, value: str) -> str:
        escaped = value.replace("%", "%25").replace(" ", "%s")
        for char in ("\\", "'", '"', "&", "<", ">", "(", ")", ";", "|", "*", "~", "`", "$"):
            escaped = escaped.replace(char, f"\\{char}")
        return escaped

    def _press_enter(self, device: Any) -> None:
        try:
            device.press("enter")
        except Exception:
            pass

    def _wait_for_login_form(self, device: Any, *, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            hierarchy = self._hierarchy(device).lower()
            if "android.widget.edittext" in hierarchy and (
                "username" in hierarchy or "email" in hierarchy or "password" in hierarchy
            ):
                return True
            try:
                if device(className="android.widget.EditText", instance=0).exists(timeout=0.5):
                    return True
            except Exception:
                pass
            self._wait(0.3)
        return False

    def _current_package(self, device: Any) -> str:
        try:
            current = device.app_current()
        except Exception:
            return ""
        if isinstance(current, dict):
            return str(current.get("package") or "")
        return ""

    def _is_instagram_foreground(self, device: Any) -> bool:
        return self._current_package(device) == INSTAGRAM_ANDROID_PACKAGE

    def _start_instagram(self, device: Any, settings: Settings, serial: str) -> None:
        try:
            device.app_start(INSTAGRAM_ANDROID_PACKAGE, wait=True)
        except Exception:
            pass
        self._wait(2)
        if self._is_instagram_foreground(device):
            return
        self._adb(
            settings,
            ["-s", serial, "shell", "am", "start", "-n", f"{INSTAGRAM_ANDROID_PACKAGE}/.activity.MainTabActivity"],
            timeout=20,
        )
        self._wait(2)
        if self._is_instagram_foreground(device):
            return
        self._adb(
            settings,
            [
                "-s",
                serial,
                "shell",
                "monkey",
                "-p",
                INSTAGRAM_ANDROID_PACKAGE,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ],
            timeout=20,
        )
        for _ in range(10):
            self._wait(1)
            if self._is_instagram_foreground(device):
                return

    def _screen_has_any(self, device: Any, markers: tuple[str, ...]) -> bool:
        text = self._hierarchy(device).lower()
        return any(marker in text for marker in markers)

    def _hierarchy(self, device: Any) -> str:
        result_queue: queue.Queue[str | Exception] = queue.Queue(maxsize=1)

        def dump() -> None:
            try:
                result_queue.put(str(device.dump_hierarchy(compressed=False)))
            except TypeError:
                result_queue.put(str(device.dump_hierarchy()))
            except Exception as exc:
                result_queue.put(exc)

        thread = threading.Thread(target=dump, daemon=True)
        thread.start()
        try:
            result = result_queue.get(timeout=8)
        except queue.Empty:
            return ""
        if isinstance(result, Exception):
            return ""
        return result

    def _display_size(self, device: Any) -> tuple[int, int]:
        try:
            size = device.window_size()
            if isinstance(size, tuple) and len(size) == 2:
                return int(size[0]), int(size[1])
            if isinstance(size, dict):
                return int(size["width"]), int(size["height"])
        except Exception:
            pass
        return 390, 844

    def _tap(self, device: Any, x: int, y: int) -> None:
        try:
            device.shell(["input", "tap", str(x), str(y)], timeout=10)
            return
        except Exception:
            pass
        device.click(x, y)

    def _capture(
        self,
        device: Any,
        context: WorkerContext,
        payload: PlatformTaskPayload,
        name: str,
        artifacts: AndroidArtifacts,
    ) -> None:
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name).strip("-")
        screenshot_path = context.artifact_root / f"instagram-native-{payload.job_id}-{safe_name}.png"
        hierarchy_path = context.artifact_root / f"instagram-native-{payload.job_id}-{safe_name}.xml"
        try:
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            device.screenshot(str(screenshot_path))
            artifacts.screenshots.append(str(screenshot_path))
        except Exception:
            pass
        try:
            hierarchy_path.write_text(self._hierarchy(device), encoding="utf-8")
            artifacts.hierarchies.append(str(hierarchy_path))
        except Exception:
            pass

    def _create_app_data_backup(
        self,
        settings: Settings,
        serial: str,
        payload: PlatformTaskPayload,
        artifacts: AndroidArtifacts,
    ) -> tuple[Path, Path]:
        backup_dir = self._backup_dir()
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        remote_name = f"instagram-{payload.account}-{timestamp}.tar.gz"
        remote_path = f"/sdcard/{remote_name}"
        local_path = backup_dir / remote_name
        latest_path = self._latest_backup_path(payload.account)
        self._adb_root(settings, serial, artifacts)
        self._adb(settings, ["-s", serial, "shell", "am", "force-stop", INSTAGRAM_ANDROID_PACKAGE], timeout=20)
        self._wait(1)
        self._delete_volatile_instagram_tmp_files(settings, serial, artifacts)
        archive = self._adb(
            settings,
            [
                "-s",
                serial,
                "shell",
                "tar",
                "-czf",
                remote_path,
                "--exclude",
                f"{INSTAGRAM_ANDROID_PACKAGE}/lib",
                "--exclude",
                f"{INSTAGRAM_ANDROID_PACKAGE}/files/ras_blobs/*.tmp",
                "-C",
                "/data/user/0",
                INSTAGRAM_ANDROID_PACKAGE,
            ],
            timeout=120,
        )
        if archive.returncode != 0:
            artifacts.adb_logs.append(archive.stdout.strip() or archive.stderr.strip())
            raise AndroidRuntimeError(
                "Instagram Android data archive command failed.",
                ErrorCode.INTERNAL_ERROR,
            )
        completed = self._adb(
            settings,
            ["-s", serial, "pull", remote_path, str(local_path)],
            timeout=120,
        )
        artifacts.adb_logs.append(completed.stdout.strip() or completed.stderr.strip())
        if completed.returncode != 0 or not local_path.exists():
            raise AndroidRuntimeError("Instagram Android data backup failed.", ErrorCode.INTERNAL_ERROR)
        latest_path.write_bytes(local_path.read_bytes())
        return local_path, latest_path

    def _delete_volatile_instagram_tmp_files(
        self,
        settings: Settings,
        serial: str,
        artifacts: AndroidArtifacts,
    ) -> None:
        completed = self._adb(
            settings,
            [
                "-s",
                serial,
                "shell",
                "find",
                f"/data/user/0/{INSTAGRAM_ANDROID_PACKAGE}/files/ras_blobs",
                "-name",
                "*.tmp",
                "-delete",
            ],
            timeout=20,
        )
        output = (completed.stdout.strip() or completed.stderr.strip()).strip()
        if output and "No such file or directory" not in output:
            artifacts.adb_logs.append(output)

    def _restore_app_data_files(
        self,
        settings: Settings,
        serial: str,
        backup: Path,
        artifacts: AndroidArtifacts,
    ) -> None:
        self._adb_root(settings, serial, artifacts)
        remote_path = f"/sdcard/{backup.name}"
        pushed = self._adb(settings, ["-s", serial, "push", str(backup), remote_path], timeout=120)
        artifacts.adb_logs.append(pushed.stdout.strip() or pushed.stderr.strip())
        if pushed.returncode != 0:
            raise AndroidRuntimeError(
                "Could not push Instagram Android backup to the device.",
                ErrorCode.INTERNAL_ERROR,
            )
        self._adb(settings, ["-s", serial, "shell", "am", "force-stop", INSTAGRAM_ANDROID_PACKAGE], timeout=20)
        self._adb(settings, ["-s", serial, "shell", "pm", "clear", INSTAGRAM_ANDROID_PACKAGE], timeout=60)
        restored = self._adb(
            settings,
            [
                "-s",
                serial,
                "shell",
                "tar",
                "-xzf",
                remote_path,
                "--exclude",
                f"{INSTAGRAM_ANDROID_PACKAGE}/lib",
                "--exclude",
                f"{INSTAGRAM_ANDROID_PACKAGE}/files/ras_blobs/*.tmp",
                "-C",
                "/data/user/0",
            ],
            timeout=120,
        )
        if restored.returncode != 0:
            artifacts.adb_logs.append(restored.stdout.strip() or restored.stderr.strip())
            raise AndroidRuntimeError("Instagram Android backup restore failed.", ErrorCode.INTERNAL_ERROR)

    def _backup_dir(self) -> Path:
        return Path("runtime/android-backups")

    def _latest_backup_path(self, account: str) -> Path:
        return self._backup_dir() / f"instagram-{account}-latest.tar.gz"

    def _adb_root(self, settings: Settings, serial: str, artifacts: AndroidArtifacts) -> None:
        completed = self._adb(settings, ["-s", serial, "root"], timeout=30)
        output = (completed.stdout.strip() or completed.stderr.strip()).strip()
        if output:
            artifacts.adb_logs.append(output)
        if completed.returncode != 0:
            raise AndroidRuntimeError(
                f"Could not restart ADB as root for Android data backup: {output}",
                ErrorCode.INTERNAL_ERROR,
            )
        self._adb(settings, ["-s", serial, "wait-for-device"], timeout=30)

    def _adb(self, settings: Settings, args: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [settings.adb_path, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def _wait(self, seconds: float) -> None:
        time.sleep(seconds)

    def _target_post_url(self, payload: PlatformTaskPayload) -> str | None:
        raw_url = payload.content.extra.get("instagram_post_url") or payload.content.extra.get("target_post_url")
        url = str(raw_url or "").strip()
        if not url:
            return None
        if "instagram.com/" not in url or ("/p/" not in url and "/reel/" not in url):
            return None
        return url

    def _failed(
        self,
        payload: PlatformTaskPayload,
        message: str,
        error_code: ErrorCode,
        artifacts: AndroidArtifacts,
        *,
        serial: str | None = None,
        auth_status: str = "failed",
    ) -> PlatformResult:
        return PlatformResult(
            platform=payload.platform,
            status="failed",
            message=message,
            error_code=error_code,
            raw=self._raw(artifacts, serial=serial, auth_status=auth_status),
        )

    def _raw(
        self,
        artifacts: AndroidArtifacts,
        *,
        serial: str | None,
        auth_status: str,
    ) -> dict[str, Any]:
        return {
            "runtime": ANDROID_RUNTIME,
            "device_serial": serial,
            "auth_status": auth_status,
            "screenshots": artifacts.screenshots,
            "hierarchies": artifacts.hierarchies,
            "adb_logs": artifacts.adb_logs,
        }
