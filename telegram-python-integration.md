# Orange Echo integration guide for a Python Telegram bot

This document describes the deployed Orange Echo API at:

```text
https://orange-echo.botbolidan.workers.dev
```

The preferred daily flow is synchronous and does not use R2:

```text
collected morning intel
  -> optimize into spoken narration
  -> generate Aura-2 Luna OGG/Opus
  -> send the OGG as a Telegram voice message
  -> optionally generate and send one image
```

## 1. Credentials and environment variables

The Python bot needs:

```dotenv
ORANGE_ECHO_BASE_URL=https://orange-echo.botbolidan.workers.dev
ORANGE_ECHO_API_KEY=oe_live_replace_with_the_real_client_key
TELEGRAM_BOT_TOKEN=replace_with_the_BotFather_token
```

`ORANGE_ECHO_API_KEY` is the client credential generated during bootstrap. The current
client has:

- `jobs:create`
- `jobs:read`
- `artifacts:read`

The synchronous inference endpoints currently use `jobs:create`.

The Telegram process does not need any of the following:

- Cloudflare account ID;
- Cloudflare API token;
- `API_KEY_PEPPER`;
- separate Llama, Deepgram, or Black Forest Labs tokens;
- R2 credentials.

The Worker invokes all models through its existing Workers AI binding. Cloudflare
deployment credentials and the API-key pepper are administrative secrets and must never
be copied into the Telegram bot.

## 2. Install the Python dependency

The examples use `httpx` because modern Telegram bot frameworks are asynchronous:

```bash
python -m pip install httpx
```

Use the Telegram framework already selected by the bot. The examples below show the
relevant `python-telegram-bot` send methods but do not require that framework for the API
client itself.

## 3. Reusable asynchronous client

```python
from __future__ import annotations

import base64
from dataclasses import dataclass

import httpx


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
    def __init__(self, base_url: str, api_key: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(120.0, connect=10.0),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def optimize(
        self,
        intel: str,
        *,
        target_characters: int = 900,
    ) -> str:
        response = await self._client.post(
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
        response = await self._client.post(
            "/v1/inference/speech",
            json={"text": narration},
        )
        self._raise_for_api_error(response)
        if response.headers.get("content-type", "").split(";", 1)[0] != "audio/ogg":
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
        response = await self._client.post(
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
        except (KeyError, TypeError, ValueError):
            code = "orange_echo_error"
            message = f"Orange Echo returned HTTP {response.status_code}"
        raise OrangeEchoError(response.status_code, code, message)
```

Create one client at bot startup and close it during shutdown. Do not create a new HTTP
client for every Telegram update.

## 4. Endpoint contracts

Every `/v1` call requires:

```http
Authorization: Bearer <ORANGE_ECHO_API_KEY>
Content-Type: application/json
```

### 4.1 Optimize morning intel

```http
POST /v1/inference/optimize
```

Request:

```json
{
  "intel": "Combined weather, news, market, and technology source material",
  "target_characters": 900
}
```

Response:

```json
{
  "narration": "Good morning. Today...",
  "characters": 742,
  "model": "@cf/meta/llama-3.1-8b-instruct-fp8-fast",
  "target_characters": 900
}
```

Limits:

- one optimization per UTC day across the service;
- 30,000 input characters;
- `target_characters` must be at least 300;
- output is capped at 1,600 characters;
- no R2 write.

The bot should combine and trim its feeds before this call. Treat the returned narration
as generated text: preserve the raw source digest locally long enough to audit important
numbers or claims.

### 4.2 Generate Aura-2 Luna speech

```http
POST /v1/inference/speech
```

Request:

```json
{
  "text": "The optimized narration"
}
```

Response:

```http
Content-Type: audio/ogg
Content-Disposition: attachment; filename="morning-briefing.ogg"
```

The body is OGG/Opus generated by:

```text
@cf/deepgram/aura-2-en
speaker: luna
encoding: opus
container: ogg
```

Limits:

- one direct speech call per UTC day across the service;
- 1,600 input characters;
- no R2 write.

### 4.3 Generate a FLUX.2 image

```http
POST /v1/inference/image
```

Request:

```json
{
  "prompt": "A clean editorial illustration for this morning's technology briefing",
  "seed": 12345
}
```

`seed` is optional.

Response:

```json
{
  "image_base64": "...",
  "mime_type": "image/jpeg",
  "model": "@cf/black-forest-labs/flux-2-klein-4b"
}
```

The deployed model uses 1024×1024 output. The MIME type may be `image/jpeg`,
`image/png`, or `image/webp`; use the returned value rather than assuming an extension.

Limits:

- one image per UTC day across the service;
- prompt length from 1 to 2,048 characters;
- no R2 write.

The hosted model is not guaranteed to be uncensored. Provider or platform policy
enforcement may reject prompts.

### 4.4 Legacy asynchronous job endpoints

The R2-backed path remains available:

- `POST /v1/jobs`
- `GET /v1/jobs/{job_id}`
- `GET /v1/artifacts/{job_id}/chunks/{chunk_index}`

Use it only when asynchronous chunking is required. Its production profile is limited to
one 2,000-character job per client per UTC day and one-day R2 expiration. The daily
briefing should use the direct inference routes instead.

## 5. Telegram delivery

With `python-telegram-bot`, send the audio bytes as a voice message:

```python
from io import BytesIO


async def send_briefing(bot, chat_id: int, echo: OrangeEchoClient, intel: str) -> None:
    narration = await echo.optimize(intel, target_characters=900)
    audio = await echo.synthesize(narration)

    voice = BytesIO(audio)
    voice.name = "morning-briefing.ogg"
    await bot.send_voice(
        chat_id=chat_id,
        voice=voice,
        caption="Morning briefing",
    )
```

Optionally generate and send an image:

```python
from io import BytesIO


async def send_briefing_image(
    bot,
    chat_id: int,
    echo: OrangeEchoClient,
    prompt: str,
) -> None:
    generated = await echo.generate_image(prompt)
    suffix = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }[generated.mime_type]
    photo = BytesIO(generated.content)
    photo.name = f"morning-briefing.{suffix}"
    await bot.send_photo(chat_id=chat_id, photo=photo)
```

The bot should derive the image prompt from the verified source digest or optimized
narration. Do not ask the image model to render stock prices, dates, or other exact text;
send exact facts in the Telegram caption instead.

## 6. Scheduling and safe retries

The counters reset at `00:00 UTC`. They are service-wide rather than per Telegram chat.
Use one scheduler and one process-level or distributed lock so two bot workers cannot
start the same daily run.

Recommended sequence:

1. collect and normalize feeds;
2. write the source digest to a private local temporary file;
3. call `optimize`;
4. immediately save the narration locally;
5. call `synthesize`;
6. immediately save the OGG locally;
7. send the saved OGG to Telegram;
8. optionally generate one image;
9. delete local temporary files according to the bot's retention policy.

Do not blindly retry a `429 quota_exceeded`. Cloudflare Workers AI free tier provides 10,000 Neurons per day across all inference operations, resetting daily at 00:00 UTC. If the limit is reached, requests will fail with `quota_exceeded` until the next 00:00 UTC reset.

It is safe to retry Telegram delivery from a locally saved OGG or image because that does
not call Orange Echo again.

## 7. Error handling

| HTTP | Code                            | Bot behavior                                              |
| ---: | ------------------------------- | --------------------------------------------------------- |
|  400 | `invalid_request`               | Log metadata, correct the request; do not retry unchanged |
|  401 | `authentication_failed`         | Stop and repair `ORANGE_ECHO_API_KEY`                     |
|  403 | `insufficient_scope`            | Stop and update the API-client scopes                     |
|  413 | `source_too_large`              | Trim input before retrying                                |
|  429 | `quota_exceeded`                | 10k daily Neurons reached; retry after 00:00 UTC          |
|  500 | `internal_error`                | Alert; check Worker logs before retrying                  |
|  502 | model-specific invalid response | Alert; check model status before retrying                 |


Never log:

- bearer tokens;
- raw private intel;
- complete generated audio or image base64;
- the API-key pepper.

Safe logs include request IDs, response status, character counts, byte counts, model
names, and elapsed time.

## 8. Local one-file proof

The repository includes:

```bash
python3 scripts/test-daily-briefing.py --input morning-intel.txt
```

Add an image only when intending to consume the day's image allowance:

```bash
python3 scripts/test-daily-briefing.py \
  --input morning-intel.txt \
  --image-prompt "A calm editorial morning briefing illustration, no text"
```

Outputs are written under the ignored `daily-briefing-output/` directory. The existing
`briefing-image.jpg` was generated by FLUX.1 Schnell before the production model changed.
A FLUX.2 Klein 4B output will appear there after running the image test following the next
UTC reset.

## 9. Remaining production-readiness work

The core pipeline works, but the Telegram integration should account for:

1. **Idempotent direct inference:** the direct endpoints do not accept an idempotency key
   or cache results. A network failure after generation can lose the output while
   consuming the daily allowance.
2. **Usage-status endpoint:** there is no authenticated endpoint for the bot to inspect
   today's optimization, speech, and image counters.
3. **Failure recovery:** there is no administrative reset or replay for a failed direct
   inference. Manual D1 changes should not become routine operations.
4. **Single-run coordination:** multiple Telegram workers need a shared scheduler lock.
5. **Local bot-side caching:** save narration, OGG, and image before Telegram delivery so
   Telegram retries do not regenerate media.
6. **Credential rotation:** create a replacement API key, deploy it to the bot, verify it,
   and then deactivate the old client.
7. **Feed provenance:** retain source names and timestamps in the bot so generated
   narration can be checked when a number sounds wrong.
8. **Monitoring:** alert on `401`, `429`, `5xx`, invalid media signatures, and missed
   scheduled runs without logging private source content.
9. **Least-privilege inference scope:** the direct routes currently reuse `jobs:create`.
   Before distributing credentials beyond the personal bot, add a dedicated
   `inference:run` scope and bootstrap a bot-only client.

The first three items are the most important Worker-side follow-up.
