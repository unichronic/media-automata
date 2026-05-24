from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from media_automata.config import Settings

ModelT = TypeVar("ModelT", bound=BaseModel)
logger = logging.getLogger(__name__)


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0
    by_model: dict[str, int] = field(default_factory=dict)


class LLMProvider(ABC):
    @abstractmethod
    async def generate_structured(self, *, system: str, user: str, model_type: type[ModelT]) -> ModelT:
        raise NotImplementedError

    @abstractmethod
    async def generate_text(self, *, system: str, user: str) -> str:
        raise NotImplementedError

    async def summarize(self, *, text: str, instruction: str = "Summarize the text.") -> str:
        return await self.generate_text(system=instruction, user=text)

    async def judge(self, *, system: str, user: str) -> str:
        return await self.generate_text(system=system, user=user)


class MistralLLMProvider(LLMProvider):
    def __init__(self, settings: Settings, *, purpose: str = "command"):
        api_keys = settings.mistral_api_keys_for(purpose)
        if not api_keys:
            raise ValueError("MISTRAL_API_KEY, MISTRAL_API_KEYS, or MISTRAL_API_KEY1-3 is required.")
        self.api_keys = api_keys
        self.purpose = purpose
        self.model = settings.llm_model
        self.base_url = "https://api.mistral.ai/v1"
        self.usage = LLMUsage()

    async def generate_structured(self, *, system: str, user: str, model_type: type[ModelT]) -> ModelT:
        schema = model_type.model_json_schema()
        schema_text = json.dumps(schema, separators=(",", ":"))
        prompt = (
            f"{user}\n\n"
            "Return a single JSON object only. It must conform to this JSON Schema:\n"
            f"{schema_text}"
        )
        last_error: Exception | None = None
        for attempt in range(1, 3):
            content = await self._chat(
                system=system,
                user=prompt,
                response_format={"type": "json_object"},
            )
            try:
                return model_type.model_validate(_json_from_text(content))
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                logger.warning("structured_output_repair model=%s attempt=%s error=%s", self.model, attempt, exc)
                prompt = (
                    f"{user}\n\n"
                    "The previous response did not validate. Return corrected JSON only.\n"
                    f"Validation error: {exc}\n"
                    f"JSON Schema: {schema_text}"
                )
        if last_error:
            raise last_error
        raise RuntimeError("Structured generation failed without an error.")

    async def generate_text(self, *, system: str, user: str) -> str:
        return await self._chat(system=system, user=user, response_format=None)

    async def _chat(self, *, system: str, user: str, response_format: dict | None) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if response_format:
            payload["response_format"] = response_format

        async with httpx.AsyncClient(timeout=90) as client:
            data = await self._post_with_retries(client, payload)
        self._record_usage(data.get("usage"))
        return data["choices"][0]["message"]["content"]

    async def _post_with_retries(self, client: httpx.AsyncClient, payload: dict[str, Any]) -> dict[str, Any]:
        max_attempts = max(3, len(self.api_keys))
        retry_statuses = {408, 409, 425, 429, 500, 502, 503, 504}
        started = time.monotonic()
        for attempt in range(1, max_attempts + 1):
            key_slot = (attempt - 1) % len(self.api_keys)
            api_key = self.api_keys[key_slot]
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if response.status_code in retry_statuses and attempt < max_attempts:
                    logger.warning(
                        "mistral_chat_retry purpose=%s model=%s attempt=%s key_slot=%s status=%s",
                        self.purpose,
                        self.model,
                        attempt,
                        key_slot,
                        response.status_code,
                    )
                    await asyncio.sleep(0.75 * attempt)
                    continue
                response.raise_for_status()
                elapsed_ms = int((time.monotonic() - started) * 1000)
                logger.info(
                    "mistral_chat_completed purpose=%s model=%s attempt=%s key_slot=%s elapsed_ms=%s",
                    self.purpose,
                    self.model,
                    attempt,
                    key_slot,
                    elapsed_ms,
                )
                return response.json()
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt == max_attempts:
                    raise
                await asyncio.sleep(0.75 * attempt)
        raise RuntimeError("Mistral request failed after retries.")

    def _record_usage(self, usage: dict[str, Any] | None) -> None:
        self.usage.requests += 1
        self.usage.by_model[self.model] = self.usage.by_model.get(self.model, 0) + 1
        if not usage:
            return
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
        self.usage.prompt_tokens += prompt_tokens
        self.usage.completion_tokens += completion_tokens
        self.usage.total_tokens += total_tokens
        logger.info(
            "mistral_usage model=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            self.model,
            prompt_tokens,
            completion_tokens,
            total_tokens,
        )


def build_llm_provider(settings: Settings, *, purpose: str = "command") -> LLMProvider:
    return MistralLLMProvider(settings, purpose=purpose)


def _json_from_text(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return json.loads(stripped)
