"""Orange Echo Cloudflare Workers AI client integration."""

from __future__ import annotations

import base64
import html
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from .models.bot_state import BotState

logger = logging.getLogger(__name__)


class OrangeEchoError(RuntimeError):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.status = status
        self.code = code
        self.raw_message = message

    def user_friendly_message(self) -> str:
        escaped_msg = html.escape(self.raw_message)
        if self.code == "quota_exceeded":
            return (
                "⚠️ <b>Cloudflare AI Daily Quota Exceeded</b>\n"
                "The daily free-tier limit of 10,000 Neurons has been reached (resets daily at 00:00 UTC).\n"
                f"<i>{escaped_msg}</i>"
            )

        elif self.code in ("unauthorized", "invalid_api_key"):
            return (
                "❌ <b>Cloudflare AI Authentication Failed</b>\n"
                f"Please check your ORANGE_ECHO_API_KEY.\n<i>{escaped_msg}</i>"
            )
        elif self.code == "rate_limit":
            return (
                "⚠️ <b>Cloudflare AI Rate Limit Reached</b>\n"
                f"Too many requests. Please try again shortly.\n<i>{escaped_msg}</i>"
            )
        else:
            return (
                f"❌ <b>Cloudflare AI Error ({html.escape(self.code)})</b>\n"
                f"<i>{escaped_msg}</i>"
            )


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


def extract_total_neurons(data: dict[str, object]) -> int:
    """Extract total used neurons count from Cloudflare allowance JSON."""
    if not isinstance(data, dict):
        return 0
    allowances = data.get("allowances")
    if isinstance(allowances, dict):
        data = allowances
    for k in ("daily_neurons", "neurons", "usage", "allowance"):
        v = data.get(k)
        if isinstance(v, dict):
            used = v.get("used")
            if used is not None:
                try:
                    return int(used)
                except TypeError, ValueError:
                    pass
    if "used" in data:
        try:
            return int(data["used"])
        except TypeError, ValueError:
            pass
    for v in data.values():
        if isinstance(v, dict) and "used" in v:
            try:
                return int(v["used"])
            except TypeError, ValueError:
                pass
    return 0


async def track_cf_action(
    client: OrangeEchoClient,
    state: BotState | None,
    action_name: str,
    action_coro: Any,
) -> Any:
    """Execute a Cloudflare AI action, checking allowance before and after to log consumed neurons."""
    neurons_before: int | None = None
    try:
        allow_before = await client.get_allowances()
        neurons_before = extract_total_neurons(allow_before)
    except Exception as exc:
        logger.debug("Failed to fetch allowances before %s: %s", action_name, exc)

    result = await action_coro

    neurons_after: int | None = None
    try:
        allow_after = await client.get_allowances()
        neurons_after = extract_total_neurons(allow_after)
    except Exception as exc:
        logger.debug("Failed to fetch allowances after %s: %s", action_name, exc)

    if neurons_before is None or neurons_after is None:
        logger.info(
            "CF Action '%s' executed; neuron usage unavailable because allowance sampling failed",
            action_name,
        )
        return result

    consumed = max(0, neurons_after - neurons_before)
    logger.info(
        "CF Action '%s' executed: used %d neurons (total today: %d)",
        action_name,
        consumed,
        neurons_after,
    )
    if state is not None:
        state.add_cf_run_log(action_name, consumed, neurons_after)

    return result
