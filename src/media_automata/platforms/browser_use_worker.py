from __future__ import annotations

import asyncio
from contextlib import suppress
from inspect import isawaitable
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel

from media_automata.platforms.base import BrowserDependencyError, PlatformWorker, WorkerContext, dependency_error_result
from media_automata.platforms.browser_use_llm import RotatingMistralBrowserUseLLM
from media_automata.platforms.profile import persistent_browser_args, prepare_persistent_profile
from media_automata.schemas import ErrorCode, PlatformResult, PlatformTaskPayload


class AuthCheckResult(BaseModel):
    status: Literal["authenticated", "login_required", "challenge_required", "failed"]
    message: str = ""
    final_url: str | None = None


class BrowserUsePlatformWorker(PlatformWorker):
    allowed_domains: list[str] = []
    auth_start_url: str = ""
    auth_success_description: str = "the logged-in application UI is visible"
    auth_login_description: str = "the platform login form is visible"
    mistral_purpose: str = "browser"

    async def publish_post(
        self,
        payload: PlatformTaskPayload,
        context: WorkerContext,
        asset_lookup: dict[str, str],
    ) -> PlatformResult:
        try:
            history = await self._run_browser_use(payload, context, asset_lookup)
        except BrowserDependencyError as exc:
            return dependency_error_result(payload, exc)
        except Exception as exc:
            return PlatformResult(
                platform=payload.platform,
                status="failed",
                message=f"Browser agent failed: {exc}",
                error_code=ErrorCode.UNKNOWN_UI_STATE,
            )
        if not history.is_successful():
            return PlatformResult(
                platform=payload.platform,
                status="failed",
                message=history.final_result() or "Browser agent did not complete the platform task.",
                error_code=ErrorCode.UNKNOWN_UI_STATE,
                raw={
                    "browser_use_history": str(history),
                },
            )
        return PlatformResult(
            platform=payload.platform,
            status="success",
            message="Browser agent completed the platform task.",
            raw={
                "browser_use_history": str(history),
            },
        )

    async def ensure_authenticated(self, payload: PlatformTaskPayload, context: WorkerContext) -> AuthCheckResult:
        history = await self._run_agent(
            task=self.auth_prompt(payload, context),
            context=context,
            output_model_schema=AuthCheckResult,
            sensitive_data=self.auth_sensitive_data(payload, context),
            max_steps=35,
        )
        structured = history.get_structured_output(AuthCheckResult)
        if structured:
            return structured
        if history.is_successful():
            return AuthCheckResult(status="authenticated", message=history.final_result() or "")
        return AuthCheckResult(status="failed", message=history.final_result() or "Authentication preflight failed.")

    async def _run_browser_use(
        self,
        payload: PlatformTaskPayload,
        context: WorkerContext,
        asset_lookup: dict[str, str],
    ) -> Any:
        return await self._run_agent(
            task=self.publish_prompt(payload, context, asset_lookup),
            context=context,
            available_file_paths=media_paths(payload, context, asset_lookup),
            sensitive_data=self.auth_sensitive_data(payload, context),
            max_steps=80,
        )

    async def _run_agent(
        self,
        *,
        task: str,
        context: WorkerContext,
        available_file_paths: list[str] | None = None,
        sensitive_data: dict[str, str | dict[str, str]] | None = None,
        output_model_schema: type[BaseModel] | None = None,
        max_steps: int,
    ) -> Any:
        try:
            from browser_use import Agent, Browser
        except Exception as exc:  # pragma: no cover - exercised only when optional dependency is absent
            raise BrowserDependencyError(
                "browser-use is not installed. Run `uv pip install -e .`."
            ) from exc

        api_keys = context.settings.mistral_api_keys_for(self.mistral_purpose)
        if not api_keys:
            raise BrowserDependencyError("MISTRAL_API_KEY, MISTRAL_API_KEYS, or MISTRAL_API_KEY1-3 is required.")
        key_ring = list(api_keys)

        last_error: Exception | None = None
        for startup_attempt in range(1, 3):
            prepare_persistent_profile(context.profile_path)
            browser = Browser(
                executable_path=playwright_chromium_executable(),
                headless=context.settings.browser_headless,
                user_data_dir=str(context.profile_path),
                window_size={"width": 1400, "height": 1000},
                allowed_domains=self.allowed_domains or None,
                args=persistent_browser_args(),
            )
            llm = RotatingMistralBrowserUseLLM(
                model=context.settings.llm_model,
                api_keys=tuple(key_ring),
                purpose=self.mistral_purpose,
            )
            agent = Agent(
                task=task,
                browser=browser,
                llm=llm,
                available_file_paths=available_file_paths or [],
                sensitive_data=sensitive_data,
                output_model_schema=output_model_schema,
                use_vision=False,
                use_judge=False,
                enable_planning=False,
                max_failures=3,
                step_timeout=context.settings.browser_timeout_seconds,
            )
            try:
                return await agent.run(max_steps=max_steps)
            except (httpx.RemoteProtocolError, TimeoutError) as exc:
                last_error = exc
                if startup_attempt == 2:
                    break
                await asyncio.sleep(2)
            finally:
                with suppress(Exception):
                    close = getattr(browser, "close", None)
                    if callable(close):
                        result = close()
                        if isawaitable(result):
                            await result
        if last_error:
            raise last_error
        raise RuntimeError("Browser Use agent failed to start.")

    def task_prompt(self, payload: PlatformTaskPayload, context: WorkerContext, asset_lookup: dict[str, str]) -> str:
        raise NotImplementedError

    def publish_prompt(
        self,
        payload: PlatformTaskPayload,
        context: WorkerContext,
        asset_lookup: dict[str, str],
    ) -> str:
        return f"""
Open {self.auth_start_url}.
Before posting, verify the current browser session is authenticated for account {payload.account}.

Authenticated signal:
{self.auth_success_description}

Logged-out signal:
{self.auth_login_description}

{self.auth_credential_instruction(payload, context)}

Login rules:
- If already authenticated, continue directly to the publishing task.
- If logged out and credentials are unavailable, stop and report login_required.
- If credentials are available, try exactly one normal login attempt.
- To log in, click the username/email/phone field and input <secret>login_identifier</secret>, then click the
  password field and input <secret>password</secret>, then submit the form.
- Prefer pressing Enter from the password field, or click an exact "Log in", "Sign in", or "Submit" button.
- Never click "Forgot password", password reset, help, sign-up, or account recovery controls.
- If MFA, OTP, captcha, suspicious login, email/phone verification, identity checkpoint, locked account,
  or manual approval appears, stop immediately and report the blocker.
- Do not attempt to bypass a challenge.

Publishing task:
{self.task_prompt(payload, context, asset_lookup)}

Return success only after the platform shows a visible published/sent/shared confirmation, post URL, or the posted
content appears in the account feed/profile. If posting cannot be confirmed, call done with success=false and explain
the blocker.
"""

    def auth_prompt(self, payload: PlatformTaskPayload, context: WorkerContext) -> str:
        credential_instruction = self.auth_credential_instruction(payload, context)
        return f"""
Open {self.auth_start_url}.
Check whether the persistent browser profile for account {payload.account} is already authenticated.

Authenticated signal:
{self.auth_success_description}

Logged-out signal:
{self.auth_login_description}

{credential_instruction}

Rules:
- If already authenticated, return status "authenticated".
- If logged out and credentials are unavailable, return status "login_required".
- If credentials are available, try exactly one normal login attempt.
- To log in, click the username/email/phone field and input <secret>login_identifier</secret>, then click the
  password field and input <secret>password</secret>, then submit the form.
- Prefer pressing Enter from the password field, or click an exact "Log in", "Sign in", or "Submit" button.
- Never click "Forgot password", password reset, help, sign-up, or account recovery controls.
- If MFA, OTP, captcha, suspicious login, email/phone verification, identity checkpoint, locked account,
  or manual approval appears, stop immediately and return status "challenge_required".
- Do not attempt to bypass a challenge.
- Return final_url when visible.
"""

    def auth_credential_instruction(self, payload: PlatformTaskPayload, context: WorkerContext) -> str:
        credentials = context.settings.platform_login_credentials(str(payload.platform))
        if credentials:
            secondary_instruction = (
                "If an intermediate normal login step asks for an alternate phone, email, username, or account "
                "identifier before the password screen, input <secret>secondary_identifier</secret>."
                if credentials.secondary_identifier
                else "If an intermediate normal login step asks for an alternate phone, email, username, or account "
                "identifier before the password screen, input <secret>login_identifier</secret>."
            )
            credential_instruction = (
                "Credential fallback is enabled. If the profile is logged out, use login_identifier and password "
                "through <secret>login_identifier</secret> and <secret>password</secret> placeholders. "
                f"{secondary_instruction}"
            )
        else:
            credential_instruction = "Credential fallback is disabled because credentials are not configured."
        return credential_instruction

    def auth_sensitive_data(
        self,
        payload: PlatformTaskPayload,
        context: WorkerContext,
    ) -> dict[str, str | dict[str, str]] | None:
        credentials = context.settings.platform_login_credentials(str(payload.platform))
        if not credentials:
            return None
        values = {"login_identifier": credentials.identifier, "password": credentials.password}
        if credentials.secondary_identifier:
            values["secondary_identifier"] = credentials.secondary_identifier
        return {domain: values for domain in self.allowed_domains}

    def _auth_failure_result(self, payload: PlatformTaskPayload, auth_result: AuthCheckResult) -> PlatformResult:
        if auth_result.status == "challenge_required":
            error_code = ErrorCode.CAPTCHA_OR_VERIFICATION
        else:
            error_code = ErrorCode.LOGIN_REQUIRED
        return PlatformResult(
            platform=payload.platform,
            status="failed",
            message=auth_result.message or f"{payload.platform} login is required before posting.",
            error_code=error_code,
            raw={
                "auth_status": auth_result.status,
                "auth_final_url": auth_result.final_url,
            },
        )


def content_text(payload: PlatformTaskPayload) -> str:
    content = payload.content
    if content.posts:
        return "\n\n".join(content.posts)
    return content.caption or content.text


def media_paths(payload: PlatformTaskPayload, context: WorkerContext, asset_lookup: dict[str, str]) -> list[str]:
    return context.asset_paths(payload.content.media_asset_ids, asset_lookup)


def playwright_chromium_executable() -> str | None:
    candidates = sorted(Path.home().glob(".cache/ms-playwright/chromium-*/chrome-linux*/chrome"), reverse=True)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None
