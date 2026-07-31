from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest
from conftest import DummyContext, DummyMessage, DummyUpdate

from tele_home_supervisor import config
from tele_home_supervisor.handlers import ai
from tele_home_supervisor.orange_echo import (
    GeneratedImage,
    OrangeEchoClient,
    OrangeEchoError,
)


async def allow_guard(update, context):
    return True


@pytest.mark.asyncio
async def test_cmd_cf_tts_success(monkeypatch):
    """Test /cf-tts command generates voice message when given prompt arguments."""
    monkeypatch.setattr(ai, "guard", allow_guard)
    monkeypatch.setattr(config, "ORANGE_ECHO_API_KEY", "oe_live_test_key")

    fake_ogg = b"OggS_fake_audio_stream_data"
    mock_synthesize = AsyncMock(return_value=fake_ogg)
    monkeypatch.setattr(OrangeEchoClient, "synthesize", mock_synthesize)

    update = DummyUpdate(chat_id=1, user_id=1)
    context = DummyContext(args=["Hello", "world", "speech", "test"])

    await ai.cmd_cftts(update, context)

    mock_synthesize.assert_called_once_with("Hello world speech test")
    assert len(update.message.voices) == 1
    voice, caption = update.message.voices[0]
    assert voice.read() == fake_ogg
    assert "Cloudflare TTS" in caption


@pytest.mark.asyncio
async def test_cmd_cf_tts_from_reply_file(monkeypatch):
    """Test /cf-tts command extracts text from a replied text document."""
    monkeypatch.setattr(ai, "guard", allow_guard)
    monkeypatch.setattr(config, "ORANGE_ECHO_API_KEY", "oe_live_test_key")

    fake_ogg = b"OggS_fake_speech_bytes"
    mock_synthesize = AsyncMock(return_value=fake_ogg)
    monkeypatch.setattr(OrangeEchoClient, "synthesize", mock_synthesize)

    update = DummyUpdate(chat_id=1, user_id=1)
    context = DummyContext(args=[])

    # Setup reply message with document
    reply_msg = DummyMessage()
    reply_msg.document = MagicMock()
    reply_msg.document.file_id = "doc123"
    update.message.reply_to_message = reply_msg

    fake_tg_file = AsyncMock()
    fake_tg_file.download_as_bytearray = AsyncMock(
        return_value=bytearray(b"Narration text from file attachment")
    )
    context.bot.get_file = AsyncMock(return_value=fake_tg_file)

    await ai.cmd_cftts(update, context)

    context.bot.get_file.assert_called_once_with("doc123")
    mock_synthesize.assert_called_once_with("Narration text from file attachment")
    assert len(update.message.voices) == 1


@pytest.mark.asyncio
async def test_cmd_cf_imagegen_success(monkeypatch):
    """Test /cf-imagegen command generates photo reply."""
    monkeypatch.setattr(ai, "guard", allow_guard)
    monkeypatch.setattr(config, "ORANGE_ECHO_API_KEY", "oe_live_test_key")

    fake_image = GeneratedImage(
        content=b"fake_jpeg_bytes",
        mime_type="image/jpeg",
        model="@cf/black-forest-labs/flux-2-klein-4b",
    )
    mock_gen_img = AsyncMock(return_value=fake_image)
    monkeypatch.setattr(OrangeEchoClient, "generate_image", mock_gen_img)

    update = DummyUpdate(chat_id=1, user_id=1)
    context = DummyContext(args=["Cyberpunk", "city", "sunset"])

    await ai.cmd_cfimagegen(update, context)

    mock_gen_img.assert_called_once_with("Cyberpunk city sunset")
    assert len(update.message.photos) == 1
    photo, caption = update.message.photos[0]
    assert photo.read() == b"fake_jpeg_bytes"
    assert "@cf/black-forest-labs/flux-2-klein-4b" in caption
    assert "Prompt: Cyberpunk city sunset" in caption


@pytest.mark.asyncio
async def test_orange_echo_client_methods():
    """Test OrangeEchoClient methods directly with mocked HTTP responses."""
    client = OrangeEchoClient(
        base_url="https://orange-echo.botbolidan.workers.dev",
        api_key="test_api_key",
    )

    # Test optimize
    resp_opt = MagicMock()
    resp_opt.is_success = True
    resp_opt.json.return_value = {
        "narration": "Optimized narration text",
        "characters": 24,
    }
    client.client.post = AsyncMock(return_value=resp_opt)

    narration = await client.optimize("Intel text", target_characters=500)
    assert narration == "Optimized narration text"

    # Test synthesize
    resp_speech = MagicMock()
    resp_speech.is_success = True
    resp_speech.headers = {"content-type": "audio/ogg"}
    resp_speech.content = b"OggS_audio_data"
    client.client.post = AsyncMock(return_value=resp_speech)

    audio = await client.synthesize("Narration text")
    assert audio == b"OggS_audio_data"

    # Test generate_image
    resp_img = MagicMock()
    resp_img.is_success = True
    resp_img.json.return_value = {
        "image_base64": base64.b64encode(b"image_content").decode("utf-8"),
        "mime_type": "image/png",
        "model": "@cf/black-forest-labs/flux-2-klein-4b",
    }
    client.client.post = AsyncMock(return_value=resp_img)

    img = await client.generate_image("A cat", seed=42)
    assert img.content == b"image_content"
    assert img.mime_type == "image/png"
    assert img.model == "@cf/black-forest-labs/flux-2-klein-4b"

    # Test error raising
    resp_err = MagicMock()
    resp_err.is_success = False
    resp_err.status_code = 429
    resp_err.json.return_value = {
        "error": {"code": "quota_exceeded", "message": "Daily limit reached"}
    }
    client.client.post = AsyncMock(return_value=resp_err)

    with pytest.raises(OrangeEchoError) as exc_info:
        await client.synthesize("test")
    assert exc_info.value.status == 429
    assert exc_info.value.code == "quota_exceeded"
    assert "Daily limit reached" in str(exc_info.value)
    assert (
        "Cloudflare AI Daily Quota Exceeded" in exc_info.value.user_friendly_message()
    )

    await client.close()


def test_orange_echo_error_user_friendly_message():
    err_quota = OrangeEchoError(429, "quota_exceeded", "Limit reached")
    assert "Daily Quota Exceeded" in err_quota.user_friendly_message()

    err_auth = OrangeEchoError(401, "unauthorized", "Bad token")
    assert "Authentication Failed" in err_auth.user_friendly_message()

    err_rate = OrangeEchoError(429, "rate_limit", "Slow down")
    assert "Rate Limit Reached" in err_rate.user_friendly_message()

    err_generic = OrangeEchoError(500, "internal_error", "Server crashed")
    assert "Cloudflare AI Error (internal_error)" in err_generic.user_friendly_message()
