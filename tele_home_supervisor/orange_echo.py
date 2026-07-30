"""Orange Echo Cloudflare Workers AI client integration."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


class OrangeEchoError(RuntimeError):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.status = status
        self.code = code


@dataclass(frozen=True)
class GeneratedImage:
    content: bytes
    mime_type: str
    model: str


class OrangeEchoClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=httpx.Timeout(self.timeout, connect=10.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def get_allowances(self) -> dict[str, object]:
        """Fetch current daily allowances / usage status."""
        response = await self.client.get("/v1/allowances")
        self._raise_for_api_error(response)
        result = response.json()
        return result if isinstance(result, dict) else {"data": result}

    async def optimize(
        self,
        intel: str,
        *,
        target_characters: int = 900,
    ) -> str:
        response = await self.client.post(
            "/v1/inference/optimize",
            json={
                "intel": intel,
                "target_characters": target_characters,
            },
        )
        self._raise_for_api_error(response)
        result = response.json()
        return result["narration"]

    async def synthesize(self, narration: str) -> bytes:
        response = await self.client.post(
            "/v1/inference/speech",
            json={"text": narration},
        )
        self._raise_for_api_error(response)
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
        if content_type != "audio/ogg":
            raise RuntimeError("Orange Echo returned an unexpected audio type")
        if not response.content.startswith(b"OggS"):
            raise RuntimeError("Orange Echo returned an invalid OGG container")
        return response.content

    async def generate_image(
        self,
        prompt: str,
        *,
        seed: int | None = None,
    ) -> GeneratedImage:
        payload: dict[str, object] = {"prompt": prompt}
        if seed is not None:
            payload["seed"] = seed
        response = await self.client.post(
            "/v1/inference/image",
            json=payload,
        )
        self._raise_for_api_error(response)
        result = response.json()
        return GeneratedImage(
            content=base64.b64decode(result["image_base64"], validate=True),
            mime_type=result["mime_type"],
            model=result["model"],
        )

    @staticmethod
    def _raise_for_api_error(response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            error = response.json()["error"]
            code = error.get("code", "orange_echo_error")
            message = error.get("message", "Orange Echo request failed")
        except KeyError, TypeError, ValueError:
            code = "orange_echo_error"
            message = f"Orange Echo returned HTTP {response.status_code}"
        raise OrangeEchoError(response.status_code, code, message)
