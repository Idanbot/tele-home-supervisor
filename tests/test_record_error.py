import pytest

from tele_home_supervisor.handlers.common import record_error


class DummyRecorder:
    def __init__(self) -> None:
        self.entries: list[tuple[str, str]] = []

    def record(self, command: str, message: str, details: str | None = None) -> None:
        self.entries.append((command, message))


@pytest.mark.asyncio
async def test_record_error_uses_default_logger() -> None:
    recorder = DummyRecorder()
    replies: list[str] = []

    async def reply(text: str, **_) -> None:
        replies.append(text)

    await record_error(recorder, "demo", "failed", RuntimeError("boom"), reply)

    assert replies
    assert "boom" in replies[0]
    assert recorder.entries
