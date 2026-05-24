from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, TypeVar, cast, overload

import httpx
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage
from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)
logger = logging.getLogger(__name__)


@dataclass
class RotatingMistralBrowserUseLLM:
    """Browser Use chat adapter using Mistral JSON mode and project key rotation.

    Browser Use's bundled Mistral adapter currently uses Mistral `json_schema` response mode for structured agent
    output. In this project, Mistral Large has been reliable with plain `json_object` mode plus an explicit schema
    instruction, so this adapter keeps Browser Use while using the request shape that works for our own agent graph.
    """

    model: str
    api_keys: tuple[str, ...]
    purpose: str = "browser"
    base_url: str = "https://api.mistral.ai/v1"
    timeout_seconds: float = 90.0
    max_tokens: int = 4096
    temperature: float = 0.2
    _verified_api_keys: bool = False

    @property
    def provider(self) -> str:
        return "mistral"

    @property
    def name(self) -> str:
        return self.model

    @property
    def model_name(self) -> str:
        return self.model

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: type, handler: Any) -> Any:
        from pydantic_core import core_schema

        return core_schema.any_schema()

    @overload
    async def ainvoke(
        self,
        messages: list[BaseMessage],
        output_format: None = None,
        **kwargs: Any,
    ) -> ChatInvokeCompletion[str]: ...

    @overload
    async def ainvoke(
        self,
        messages: list[BaseMessage],
        output_format: type[ModelT],
        **kwargs: Any,
    ) -> ChatInvokeCompletion[ModelT]: ...

    async def ainvoke(
        self,
        messages: list[BaseMessage],
        output_format: type[ModelT] | None = None,
        **kwargs: Any,
    ) -> ChatInvokeCompletion[ModelT] | ChatInvokeCompletion[str]:
        if not self.api_keys:
            raise ModelProviderError("No Mistral API keys configured.", status_code=401, model=self.model)

        validation_error: Exception | None = None
        for validation_attempt in range(1, 3):
            payload = self._payload(messages, output_format, validation_error)
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                data = await self._post_with_retries(client, payload)

            content = data["choices"][0]["message"].get("content") or ""
            usage = self._usage(data.get("usage"))
            if output_format is None:
                return ChatInvokeCompletion(completion=content, usage=usage)

            try:
                parsed_json = _normalize_browser_use_output(_json_from_text(content))
                parsed = output_format.model_validate(parsed_json)
                return ChatInvokeCompletion(completion=parsed, usage=usage)
            except (json.JSONDecodeError, ValidationError) as exc:
                validation_error = exc
                logger.warning(
                    "browser_use_mistral_validation_failed purpose=%s model=%s attempt=%s error=%s",
                    self.purpose,
                    self.model,
                    validation_attempt,
                    exc,
                )

        raise ModelProviderError(f"Mistral output did not validate: {validation_error}", model=self.model)

    def _payload(
        self,
        messages: list[BaseMessage],
        output_format: type[BaseModel] | None,
        validation_error: Exception | None,
    ) -> dict[str, Any]:
        payload_messages = self._serialize_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": payload_messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if output_format is not None:
            schema_text = json.dumps(output_format.model_json_schema(), separators=(",", ":"))
            instruction = (
                "Return a single JSON object only. Do not include markdown fences or commentary. "
                "The object must conform to this JSON Schema:\n"
                f"{schema_text}"
            )
            if validation_error:
                instruction = (
                    "The previous response did not validate. Return corrected JSON only.\n"
                    f"Validation error: {validation_error}\n"
                    f"{instruction}"
                )
            payload["messages"].append({"role": "user", "content": instruction})
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _serialize_messages(self, messages: list[BaseMessage]) -> list[dict[str, Any]]:
        serialized: list[dict[str, Any]] = []
        for message in OpenAIMessageSerializer.serialize_messages(messages):
            dumper = getattr(message, "model_dump", None)
            item = cast(dict[str, Any], dumper(exclude_none=True) if callable(dumper) else dict(message))
            content = item.get("content")
            if isinstance(content, list):
                item["content"] = "\n".join(
                    part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
                )
            serialized.append(item)
        return serialized

    async def _post_with_retries(self, client: httpx.AsyncClient, payload: dict[str, Any]) -> dict[str, Any]:
        retry_statuses = {408, 409, 425, 429, 500, 502, 503, 504}
        max_attempts = max(3, len(self.api_keys) * 2)
        last_status = 0
        last_message = ""
        started = time.monotonic()

        for attempt in range(1, max_attempts + 1):
            key_slot = (attempt - 1) % len(self.api_keys)
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_keys[key_slot]}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if response.status_code >= 400:
                    last_status = response.status_code
                    last_message = self._error_message(response)
                    if response.status_code in retry_statuses and attempt < max_attempts:
                        logger.warning(
                            "browser_use_mistral_retry purpose=%s model=%s attempt=%s key_slot=%s status=%s",
                            self.purpose,
                            self.model,
                            attempt,
                            key_slot,
                            response.status_code,
                        )
                        await asyncio.sleep(0.75 * attempt)
                        continue
                    if response.status_code == 429:
                        raise ModelRateLimitError(last_message, status_code=response.status_code, model=self.model)
                    raise ModelProviderError(last_message, status_code=response.status_code, model=self.model)

                elapsed_ms = int((time.monotonic() - started) * 1000)
                logger.info(
                    "browser_use_mistral_completed purpose=%s model=%s attempt=%s key_slot=%s elapsed_ms=%s",
                    self.purpose,
                    self.model,
                    attempt,
                    key_slot,
                    elapsed_ms,
                )
                return response.json()
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_message = str(exc)
                if attempt == max_attempts:
                    raise ModelProviderError(last_message, model=self.model) from exc
                await asyncio.sleep(0.75 * attempt)

        if last_status == 429:
            raise ModelRateLimitError(last_message, status_code=429, model=self.model)
        raise ModelProviderError(
            last_message or "Mistral request failed after retries.",
            status_code=last_status,
            model=self.model,
        )

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            body = response.json()
            if isinstance(body, dict):
                error = body.get("error")
                if isinstance(error, dict):
                    return str(error.get("message") or error.get("detail") or error)
                for key in ("message", "detail"):
                    if body.get(key):
                        return str(body[key])
        except Exception:
            pass
        return response.text

    @staticmethod
    def _usage(usage: dict[str, Any] | None) -> ChatInvokeUsage | None:
        if not usage:
            return None
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        return ChatInvokeUsage(
            prompt_tokens=prompt_tokens,
            prompt_cached_tokens=None,
            prompt_cache_creation_tokens=None,
            prompt_image_tokens=None,
            completion_tokens=completion_tokens,
            total_tokens=int(usage.get("total_tokens") or prompt_tokens + completion_tokens),
        )


def _json_from_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return json.loads(stripped)


def _normalize_browser_use_output(parsed: dict[str, Any]) -> dict[str, Any]:
    """Repair common wrapper duplication from JSON-mode models.

    Browser Use action items are shaped like {"click": {"index": 1}}. Mistral JSON mode sometimes repeats the
    action name one level deeper, e.g. {"click": {"click": {"index": 1}}}. That validates as JSON but not as the
    Browser Use schema, so normalize it before Pydantic validation.
    """
    actions = parsed.get("action")
    if not isinstance(actions, list):
        return parsed

    normalized_actions: list[Any] = []
    for action in actions:
        normalized_actions.append(_normalize_action_wrapper(action))
    return {**parsed, "action": normalized_actions}


def _normalize_action_wrapper(action: Any) -> Any:
    if not isinstance(action, dict) or len(action) != 1:
        return action
    name, value = next(iter(action.items()))
    if not isinstance(name, str) or not isinstance(value, dict):
        return action
    repeated = value.get(name)
    if isinstance(repeated, dict) and set(value.keys()) == {name}:
        return {name: repeated}
    return action
