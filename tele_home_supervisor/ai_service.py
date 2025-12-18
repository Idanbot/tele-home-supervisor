"""Async Ollama client service."""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

import httpx

logger = logging.getLogger(__name__)


class OllamaClient:
    """Async client for Ollama API."""

    def __init__(
        self,
        base_url: str,
        model: str,
        system_prompt: str,
        timeout: float = 60.0,
        temp: float = 0.5,
        top_k: int = 80,
        top_p: float = 0.92,
        num_predict: int = 512,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.system_prompt = system_prompt
        self.timeout = timeout
        self.params = {
            "temperature": temp,
            "top_k": top_k,
            "top_p": top_p,
            "num_predict": num_predict,
            "repeat_penalty": 1.2,
        }

    async def generate_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        """Stream response from Ollama.

        Yields:
            Chunks of text as they are generated.
        """
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "system": self.system_prompt,
            **self.params,
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

            except httpx.HTTPError as e:
                logger.error(f"Ollama request failed: {e}")
                raise RuntimeError(f"Ollama request failed: {e}") from e
