import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from tele_home_supervisor.ai_service import (
    GenerationTarget,
    OllamaClient,
    create_text_provider,
)


def test_create_text_provider_ollama():
    target = GenerationTarget(
        provider="ollama",
        model="llama3",
        system_prompt="You are an AI",
        base_url="http://localhost:11434",
    )
    client = create_text_provider(target)
    assert isinstance(client, OllamaClient)
    assert client.base_url == "http://localhost:11434"


def test_create_text_provider_ollama_missing_url():
    target = GenerationTarget(
        provider="ollama", model="llama3", system_prompt="You are an AI", base_url=""
    )
    with pytest.raises(ValueError):
        create_text_provider(target)


def test_create_text_provider_invalid():
    target = GenerationTarget(
        provider="invalid",
        model="llama3",
        system_prompt="You are an AI",
    )
    with pytest.raises(ValueError):
        create_text_provider(target)


def _make_stream_cm(mock_response):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_response)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


async def _aiter_lines(lines):
    for line in lines:
        yield line


@pytest.mark.asyncio
@patch("tele_home_supervisor.ai_service.httpx.AsyncClient")
async def test_ollama_generate_stream(mock_client_class):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = MagicMock(
        return_value=_aiter_lines(
            [
                json.dumps({"response": "Hello ", "done": False}),
                json.dumps({"response": "world", "done": False}),
                "not json",
                json.dumps({"response": "!", "done": True}),
                json.dumps({"response": "extra", "done": False}),
            ]
        )
    )
    mock_client.stream = MagicMock(return_value=_make_stream_cm(mock_response))

    client = OllamaClient(
        base_url="http://localhost:11434",
        model="llama3",
        system_prompt="system",
    )

    chunks = []
    async for chunk in client.generate_stream("hi"):
        chunks.append(chunk)

    assert chunks == ["Hello ", "world", "!"]


@pytest.mark.asyncio
@patch("tele_home_supervisor.ai_service.httpx.AsyncClient")
async def test_ollama_generate_stream_http_error(mock_client_class):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(side_effect=httpx.HTTPError("failed"))
    mock_response.aiter_lines = MagicMock(return_value=_aiter_lines([]))
    mock_client.stream = MagicMock(return_value=_make_stream_cm(mock_response))

    client = OllamaClient(
        base_url="http://localhost:11434",
        model="llama3",
        system_prompt="system",
    )

    with pytest.raises(RuntimeError):
        async for _ in client.generate_stream("hi"):
            pass
