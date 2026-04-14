"""Provider-agnostic AI text streaming services."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Protocol

import httpx

logger = logging.getLogger(__name__)


class TextStreamProvider(Protocol):
    """Minimal interface for providers that stream text generation."""

    async def generate_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        """Yield partial response chunks for *prompt*."""


@dataclass(slots=True)
class GenerationTarget:
    """Resolved generation target for the active provider."""

    provider: str
    model: str
    system_prompt: str
    base_url: str | None = None
    api_key: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


class OllamaClient:
    """Async client for Ollama API."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        system_prompt: str,
        timeout: float = 90.0,
        temp: float = 0.25,
        top_k: int = 30,
        top_p: float = 0.85,
        num_predict: int = 320,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.system_prompt = system_prompt
        self.timeout = timeout
        self.options = {
            "temperature": temp,
            "top_k": top_k,
            "top_p": top_p,
            "num_predict": num_predict,
            "repeat_penalty": 1.1,
            "num_thread": 4,
            "num_ctx": 4000,
        }

    async def generate_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        """Stream response from Ollama."""
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "system": self.system_prompt,
            "options": dict(self.options),
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                async with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue

                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        token = chunk.get("response", "")
                        if token:
                            yield token

                        if chunk.get("done", False):
                            break

            except httpx.HTTPError as exc:
                logger.error("Ollama request failed: %s", exc)
                raise RuntimeError(f"Ollama request failed: {exc}") from exc


def create_text_provider(target: GenerationTarget) -> TextStreamProvider:
    """Construct a streaming provider for *target*."""
    provider = target.provider.strip().lower()

    if provider == "ollama":
        if not target.base_url:
            raise ValueError("Ollama target requires base_url")
        return OllamaClient(
            base_url=target.base_url,
            model=target.model,
            system_prompt=target.system_prompt,
            **target.options,
        )

    raise ValueError(f"Unsupported AI provider: {target.provider}")
