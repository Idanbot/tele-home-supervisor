from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from conftest import DummyContext, DummyUpdate

from tele_home_supervisor.handlers import docker
from tele_home_supervisor.handlers.common import get_state
from tele_home_supervisor.models.cache import CacheEntry


async def allow_guard(update, context):
    return True


@pytest.mark.asyncio
async def test_docker_commands_success_paths(monkeypatch):
    monkeypatch.setattr(docker, "guard_sensitive", allow_guard)
    monkeypatch.setattr(
        docker.services,
        "container_names",
        AsyncMock(return_value={"app"}),
    )
    monkeypatch.setattr(
        docker.services,
        "list_containers",
        AsyncMock(
            return_value=[
                {
                    "name": "app",
                    "status": "running",
                    "image": "app:latest",
                    "ports": "80",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        docker.services,
        "container_stats_rich",
        AsyncMock(
            return_value=[
                {
                    "name": "app",
                    "cpu": "1%",
                    "mem_pct": "2%",
                    "mem_usage": "20MB/1GB",
                    "netio": "1KB/2KB",
                    "blockio": "3KB/4KB",
                    "pids": "5",
                }
            ]
        ),
    )
    monkeypatch.setattr(docker.view, "render_docker_stats_chart", lambda stats: None)
    monkeypatch.setattr(
        docker.services, "healthcheck_container", AsyncMock(return_value="healthy")
    )
    monkeypatch.setattr(
        docker.services, "get_listening_ports", AsyncMock(return_value="LISTEN")
    )
    monkeypatch.setattr(
        docker.services, "get_container_inspect", AsyncMock(return_value={"Id": "abc"})
    )
    monkeypatch.setattr(
        docker, "_get_log_lines", AsyncMock(return_value=["a", "b", "c"])
    )

    update = DummyUpdate(chat_id=1, user_id=1)
    docs = []

    async def reply_document(document, **kwargs):
        docs.append(document)

    update.message.reply_document = reply_document
    context = DummyContext()
    state = get_state(context.application)
    state.caches["containers"] = CacheEntry(updated_at=999999999.0, items={"app"})

    await docker.cmd_docker(update, context)
    await docker.cmd_dockerstats(update, context)
    context.args = ["app", "1"]
    await docker.cmd_dlogs(update, context)
    context.args = ["app", "--file"]
    await docker.cmd_dlogs(update, context)
    context.args = ["app"]
    await docker.cmd_dhealth(update, context)
    await docker.cmd_ports(update, context)
    await docker.cmd_dinspect(update, context)

    replies = "\n".join(update.message.replies)
    assert "app" in replies
    assert "healthy" in replies
    assert "Listening Ports" in replies
    assert "Docker Inspect" in replies
    assert docs and docs[0].name == "app-logs.txt"


@pytest.mark.asyncio
async def test_docker_usage_error_and_large_inspect_paths(monkeypatch):
    monkeypatch.setattr(docker, "guard_sensitive", allow_guard)
    monkeypatch.setattr(
        docker.services, "container_names", AsyncMock(return_value={"app"})
    )
    monkeypatch.setattr(
        docker.services,
        "get_container_inspect",
        AsyncMock(return_value={"big": "x" * 4000}),
    )

    update = DummyUpdate(chat_id=1, user_id=1)
    docs = []

    async def reply_document(document, **kwargs):
        docs.append(document)

    update.message.reply_document = reply_document
    context = DummyContext()
    state = get_state(context.application)
    state.caches["containers"] = CacheEntry(updated_at=999999999.0, items={"app"})

    await docker.cmd_dlogs(update, DummyContext(args=["app", "--since", "bad"]))
    await docker.cmd_dhealth(update, context)
    await docker.cmd_dinspect(update, context)
    context.args = ["app"]
    await docker.cmd_dinspect(update, context)

    replies = "\n".join(update.message.replies)
    assert "Invalid --since" in replies
    assert "/dhealth" in replies
    assert "/dinspect" in replies
    assert docs and docs[0].name == "app-inspect.json"


def test_dlogs_arg_parsing_and_since_formats(monkeypatch):
    monkeypatch.setattr(docker.time, "time", lambda: 1_700_000_000)

    assert docker._parse_since("") is None
    assert docker._parse_since("60") == 1_699_999_940
    assert docker._parse_since("2m") == 1_699_999_880
    assert docker._parse_since("2026-01-01T00:00:00+00:00") == 1_767_225_600
    assert docker._parse_since("bad") is None

    parsed = docker._parse_dlogs_args(["app", "2", "--since=1h", "--file"])
    assert parsed.container == "app"
    assert parsed.page == 1
    assert parsed.as_file is True
    assert parsed.invalid_since is False
    assert docker._parse_dlogs_args(["app", "--since"]).invalid_since is True
