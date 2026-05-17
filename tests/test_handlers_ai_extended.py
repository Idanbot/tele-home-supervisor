from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from conftest import DummyContext, DummyUpdate

from tele_home_supervisor.handlers import ai


class AiContext(DummyContext):
    def __init__(self, args=None) -> None:
        super().__init__(args=args)
        self.user_data = {}


async def allow_guard(update, context):
    return True


@pytest.mark.asyncio
async def test_ollama_setting_commands(monkeypatch):
    monkeypatch.setattr(ai, "guard", allow_guard)
    update = DummyUpdate(chat_id=1, user_id=1)
    context = AiContext()

    await ai.cmd_ask(update, context)
    await ai.cmd_ollamahost(update, context)
    context.args = ["bad-host"]
    await ai.cmd_ollamahost(update, context)
    context.args = ["http://ollama:11434"]
    await ai.cmd_ollamahost(update, context)
    await ai.cmd_ollamamodel(update, AiContext())
    context.args = ["llama3.2"]
    await ai.cmd_ollamamodel(update, context)
    await ai.cmd_ollamashow(update, context)
    await ai.cmd_askreset(update, context)
    await ai.cmd_ollamareset(update, context)

    replies = "\n".join(update.message.replies)
    assert "Usage: /ask" in replies
    assert "Current host" in replies
    assert "Example" in replies
    assert "host set" in replies
    assert "Current model" in replies
    assert "model set" in replies
    assert "Ollama settings" in replies
    assert "reset" in replies


@pytest.mark.asyncio
async def test_ollama_list_status_and_cancel(monkeypatch):
    monkeypatch.setattr(ai, "guard", allow_guard)
    update = DummyUpdate(chat_id=1, user_id=1)
    context = AiContext()

    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = {"models": [{"name": "llama"}, {"name": "mistral"}]}
    client = AsyncMock()
    client.__aenter__.return_value.get.return_value = response
    monkeypatch.setattr(ai.httpx, "AsyncClient", Mock(return_value=client))

    await ai.cmd_ollamalist(update, context)
    await ai.cmd_ollamastatus(update, context)

    task = Mock()
    task.done.return_value = False
    context.application.bot_data[ai._OLLAMA_PULL_KEY] = {
        "task": task,
        "model": "llama",
        "host": "http://host",
        "status": "downloading",
        "total": 2048,
        "completed": 1024,
        "speed": 512,
        "eta": 10,
        "started_at": ai.time.monotonic(),
    }
    await ai.cmd_ollamastatus(update, context)
    await ai.cmd_ollamacancel(update, context)

    replies = "\n".join(update.message.replies)
    assert "llama" in replies
    assert "No active Ollama download" in replies
    assert "Progress: 50.0%" in replies
    assert "Cancel requested" in replies
    task.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_ollama_pull_starts_background_task(monkeypatch):
    monkeypatch.setattr(ai, "guard", allow_guard)
    created = Mock()
    created.add_done_callback = Mock()
    monkeypatch.setattr(ai.asyncio, "create_task", Mock(return_value=created))
    monkeypatch.setattr(ai, "_run_ollama_pull", Mock(return_value=object()))

    update = DummyUpdate(chat_id=1, user_id=1)
    context = AiContext(args=["llama"])

    await ai.cmd_ollamapull(update, context)

    assert context.application.bot_data[ai._OLLAMA_PULL_KEY]["model"] == "llama"
    created.add_done_callback.assert_called_once()


@pytest.mark.asyncio
async def test_busy_reply_blocks_commands(monkeypatch):
    monkeypatch.setattr(ai, "guard", allow_guard)
    update = DummyUpdate(chat_id=1, user_id=1)
    context = AiContext(args=["question"])
    task = Mock()
    task.done.return_value = False
    context.application.bot_data[ai._OLLAMA_PULL_KEY] = {
        "task": task,
        "model": "llama",
        "host": "http://host",
        "status": "pulling",
    }

    await ai.cmd_ask(update, context)

    assert "busy downloading" in update.message.replies[-1]


def test_ai_helpers_parse_flags_and_format_status():
    user_data = {
        "ollama_params": {"temp": 0.3},
        "ollama_host": "http://h",
        "ollama_model": "m",
    }
    prompt, overrides = ai._parse_generation_flags(
        [
            "--temp",
            "2",
            "--top-k",
            "5",
            "--top-p",
            "0.1",
            "--num-predict",
            "999",
            "hello",
        ],
        user_data,
    )

    assert prompt == "hello"
    assert overrides == {"temp": 1.2, "top_k": 10, "top_p": 0.5, "num_predict": 640}
    assert ai._format_text("", done=False) == "⏳ thinking..."
    assert ai._format_text("hi", done=False).endswith("▌")
    assert ai._close_unbalanced_fences("```python") == "```python\n```"
    assert ai._format_bytes(2048) == "2.0 KiB"
    assert ai._format_eta(3661) == "1h 1m"
    target = ai._resolve_generation_target(
        user_data=user_data,
        system_prompt="sys",
        overrides=overrides,
    )
    assert target.base_url == "http://h"
    assert target.model == "m"
