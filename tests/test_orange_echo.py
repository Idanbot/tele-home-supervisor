from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, Mock, patch

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

    mock_synthesize.assert_called_once_with(
        "Hello world speech test", model="premium", voice_preset="luna"
    )
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
    mock_synthesize.assert_called_once_with(
        "Narration text from file attachment",
        model="premium",
        voice_preset="luna",
    )
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

    mock_gen_img.assert_called_once_with("Cyberpunk city sunset", model="fast")
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

    narration = await client.optimize(
        "Intel text",
        target_characters=500,
        stoic_quote={"text": "Keep the quote exact.", "author": "Tester"},
    )
    assert narration == "Optimized narration text"
    assert client.client.post.call_args.kwargs["json"]["stoic_quote"]["text"] == (
        "Keep the quote exact."
    )

    # Test synthesize
    resp_speech = MagicMock()
    resp_speech.is_success = True
    resp_speech.headers = {"content-type": "audio/ogg"}
    resp_speech.content = b"OggS_audio_data"
    client.client.post = AsyncMock(return_value=resp_speech)

    audio = await client.synthesize(
        "Narration text", model="balanced", voice_preset="draco"
    )
    assert audio == b"OggS_audio_data"
    assert client.client.post.call_args.kwargs["json"]["model"] == "balanced"
    assert client.client.post.call_args.kwargs["json"]["voice_preset"] == "draco"

    # Test generate_image
    resp_img = MagicMock()
    resp_img.is_success = True
    resp_img.json.return_value = {
        "image_base64": base64.b64encode(b"image_content").decode("utf-8"),
        "mime_type": "image/png",
        "model": "@cf/black-forest-labs/flux-2-klein-4b",
    }
    client.client.post = AsyncMock(return_value=resp_img)

    img = await client.generate_image("A cat", seed=42, model="quality")
    assert img.content == b"image_content"
    assert img.mime_type == "image/png"
    assert img.model == "@cf/black-forest-labs/flux-2-klein-4b"
    assert client.client.post.call_args.kwargs["json"]["model"] == "quality"

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


@pytest.mark.asyncio
async def test_synthesize_retries_legacy_payload_for_old_worker():
    client = OrangeEchoClient(base_url="https://example.test", api_key="test_api_key")
    rejected = MagicMock()
    rejected.is_success = False
    rejected.status_code = 400
    rejected.json.return_value = {
        "error": {"code": "invalid_request", "message": "Unknown field"}
    }
    accepted = MagicMock()
    accepted.is_success = True
    accepted.headers = {"content-type": "audio/ogg"}
    accepted.content = b"OggS_legacy_audio"
    client.client.post = AsyncMock(side_effect=[rejected, accepted])

    audio = await client.synthesize(
        "Morning briefing", model="premium", voice_preset="draco"
    )

    assert audio == b"OggS_legacy_audio"
    assert client.client.post.await_args_list[0].kwargs["json"] == {
        "text": "Morning briefing",
        "model": "premium",
        "voice_preset": "draco",
    }
    assert client.client.post.await_args_list[1].kwargs["json"] == {
        "text": "Morning briefing"
    }
    await client.close()


def test_cf_model_preferences_are_persistent(tmp_path):
    from tele_home_supervisor.models.bot_state import BotState

    database = tmp_path / "state.sqlite3"
    state = BotState(_database_file=database)
    assert state.get_cf_model(7, "speech") == "premium"
    assert state.get_cf_model(7, "image") == "fast"

    state.set_cf_model(7, "speech", "balanced")
    state.set_cf_model(7, "image", "quality")

    restored = BotState(_database_file=database)
    restored.load_state()
    assert restored.get_cf_model(7, "speech") == "balanced"
    assert restored.get_cf_model(7, "image") == "quality"

    state.set_cf_voice_preset(7, "athena", "balanced")
    restored = BotState(_database_file=database)
    restored.load_state()
    assert restored.get_cf_voice(7) == "athena"
    assert restored.get_cf_model(7, "speech") == "balanced"


def test_cf_model_keyboard_uses_shared_relative_ratings():
    from tele_home_supervisor.models.bot_state import BotState
    from tele_home_supervisor.orange_echo import FALLBACK_MODELS

    keyboard = ai.build_cf_models_keyboard(BotState(), 1, FALLBACK_MODELS)
    labels = [row[0].text for row in keyboard.inline_keyboard]

    assert any("Aura-1 Angus · ~2,182 neurons · 1Q" in label for label in labels)
    assert any("Aura-2 Luna · ~4,364 neurons · 1.3Q" in label for label in labels)
    assert any("FLUX.2 Klein 4B · ~104 neurons · 1.3Q" in label for label in labels)


@pytest.mark.asyncio
async def test_cf_model_callback_persists_valid_selection(monkeypatch):
    from tele_home_supervisor.models.bot_state import BotState
    from tele_home_supervisor.orange_echo import FALLBACK_MODELS

    state = BotState()
    monkeypatch.setattr(ai, "get_state", lambda application: state)
    monkeypatch.setattr(
        ai, "_load_cf_model_catalog", AsyncMock(return_value=FALLBACK_MODELS)
    )
    monkeypatch.setattr(OrangeEchoClient, "close", AsyncMock())

    update = DummyUpdate(chat_id=1, user_id=1)
    update.callback_query = MagicMock()
    update.callback_query.data = "cfmodel:image:quality"
    update.callback_query.edit_message_text = AsyncMock()
    context = DummyContext()

    with patch.object(state, "save") as save:
        await ai.handle_cf_model_callback(update, context)

    assert state.get_cf_model(1, "image") == "quality"
    save.assert_called_once_with(force=True)
    update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_speech_model_callback_resets_to_matching_voice(monkeypatch):
    from tele_home_supervisor.models.bot_state import BotState
    from tele_home_supervisor.orange_echo import FALLBACK_MODELS

    state = BotState()
    with patch.object(state, "save"):
        state.set_cf_voice(1, "draco")
    monkeypatch.setattr(ai, "get_state", lambda application: state)
    monkeypatch.setattr(
        ai, "_load_cf_model_catalog", AsyncMock(return_value=FALLBACK_MODELS)
    )
    monkeypatch.setattr(OrangeEchoClient, "close", AsyncMock())

    update = DummyUpdate(chat_id=1, user_id=1)
    update.callback_query = MagicMock()
    update.callback_query.data = "cfmodel:speech:balanced"
    update.callback_query.edit_message_text = AsyncMock()

    with patch.object(state, "save"):
        await ai.handle_cf_model_callback(update, DummyContext())

    assert state.get_cf_model(1, "speech") == "balanced"
    assert state.get_cf_voice(1) == "angus"


@pytest.mark.asyncio
async def test_cf_voice_callback_persists_valid_selection(monkeypatch):
    from tele_home_supervisor.models.bot_state import BotState
    from tele_home_supervisor.orange_echo import FALLBACK_VOICE_PRESETS

    state = BotState()
    monkeypatch.setattr(ai, "get_state", lambda application: state)
    monkeypatch.setattr(
        ai, "_load_cf_voice_presets", AsyncMock(return_value=FALLBACK_VOICE_PRESETS)
    )
    monkeypatch.setattr(OrangeEchoClient, "close", AsyncMock())

    update = DummyUpdate(chat_id=1, user_id=1)
    update.callback_query = MagicMock()
    update.callback_query.data = "cfvoice:draco"
    update.callback_query.edit_message_text = AsyncMock()

    with patch.object(state, "save") as save:
        await ai.handle_cf_voice_callback(update, DummyContext())

    assert state.get_cf_voice(1) == "draco"
    assert state.get_cf_model(1, "speech") == "premium"
    save.assert_called_once_with(force=True)


@pytest.mark.asyncio
async def test_cf_voice_callback_ignores_already_selected_preset(monkeypatch):
    from tele_home_supervisor.models.bot_state import BotState
    from tele_home_supervisor.orange_echo import FALLBACK_VOICE_PRESETS

    state = BotState()
    with patch.object(state, "save"):
        state.set_cf_voice_preset(1, "draco", "premium")
    load_presets = AsyncMock(return_value=FALLBACK_VOICE_PRESETS)
    monkeypatch.setattr(ai, "get_state", lambda application: state)
    monkeypatch.setattr(ai, "_load_cf_voice_presets", load_presets)

    update = DummyUpdate(chat_id=1, user_id=1)
    update.callback_query = MagicMock()
    update.callback_query.data = "cfvoice:draco"
    update.callback_query.edit_message_text = AsyncMock()

    with patch.object(state, "save") as save:
        await ai.handle_cf_voice_callback(update, DummyContext())

    load_presets.assert_not_awaited()
    save.assert_not_called()
    update.callback_query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_aura1_cf_voice_callback_switches_to_balanced(monkeypatch):
    from tele_home_supervisor.models.bot_state import BotState
    from tele_home_supervisor.orange_echo import FALLBACK_VOICE_PRESETS

    state = BotState()
    monkeypatch.setattr(ai, "get_state", lambda application: state)
    monkeypatch.setattr(
        ai, "_load_cf_voice_presets", AsyncMock(return_value=FALLBACK_VOICE_PRESETS)
    )
    monkeypatch.setattr(OrangeEchoClient, "close", AsyncMock())

    update = DummyUpdate(chat_id=1, user_id=1)
    update.callback_query = MagicMock()
    update.callback_query.data = "cfvoice:athena"
    update.callback_query.edit_message_text = AsyncMock()

    with patch.object(state, "save"):
        await ai.handle_cf_voice_callback(update, DummyContext())

    assert state.get_cf_voice(1) == "athena"
    assert state.get_cf_model(1, "speech") == "balanced"


def test_orange_echo_error_user_friendly_message():
    err_quota = OrangeEchoError(429, "quota_exceeded", "Limit reached")
    assert "Daily Quota Exceeded" in err_quota.user_friendly_message()

    err_auth = OrangeEchoError(401, "unauthorized", "Bad token")
    assert "Authentication Failed" in err_auth.user_friendly_message()

    err_rate = OrangeEchoError(429, "rate_limit", "Slow down")
    assert "Rate Limit Reached" in err_rate.user_friendly_message()

    err_generic = OrangeEchoError(500, "internal_error", "Server crashed")
    assert "Cloudflare AI Error (internal_error)" in err_generic.user_friendly_message()


def test_extract_total_neurons():
    from tele_home_supervisor.orange_echo import extract_total_neurons

    assert (
        extract_total_neurons(
            {"daily_neurons": {"used": 1200, "limit": 10000, "remaining": 8800}}
        )
        == 1200
    )
    assert extract_total_neurons({"used": 500}) == 500
    assert extract_total_neurons({"unknown": "data"}) == 0


@pytest.mark.asyncio
async def test_track_cf_action():
    from tele_home_supervisor.models.bot_state import BotState
    from tele_home_supervisor.orange_echo import track_cf_action

    client = Mock()
    client.get_allowances = AsyncMock(
        side_effect=[
            {"daily_neurons": {"used": 100}},
            {"daily_neurons": {"used": 250}},
        ]
    )

    async def dummy_coro():
        return "result"

    state = BotState()
    res = await track_cf_action(client, state, "Test Action", dummy_coro())
    assert res == "result"
    assert len(state.cf_run_logs) == 1
    assert state.cf_run_logs[0].action == "Test Action"
    assert state.cf_run_logs[0].neurons_used == 150
    assert state.cf_run_logs[0].total_used_after == 250


@pytest.mark.asyncio
async def test_track_cf_action_skips_log_when_allowance_sample_fails():
    from tele_home_supervisor.models.bot_state import BotState
    from tele_home_supervisor.orange_echo import track_cf_action

    client = Mock()
    client.get_allowances = AsyncMock(
        side_effect=[
            RuntimeError("allowance endpoint unavailable"),
            {"allowances": {"neurons": {"used": 250}}},
        ]
    )
    state = BotState()

    result = await track_cf_action(client, state, "Test Action", _result("ok"))

    assert result == "ok"
    assert state.cf_run_logs == []


async def _result(value):
    return value


def test_format_allowances_accepts_string_counts():
    text = ai._format_allowances_json(
        {
            "allowances": {
                "neurons": {"used": "1200", "limit": "10000", "remaining": "8800"}
            }
        }
    )

    assert "1,200 / 10,000 neurons" in text
    assert "remaining: 8,800 neurons" in text
