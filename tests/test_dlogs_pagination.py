import pytest

from tele_home_supervisor.handlers import callbacks, docker


class DummyMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []
        self.documents: list[object] = []

    async def reply_text(self, text: str, **_) -> None:
        self.replies.append(text)

    async def reply_document(self, document, **_) -> None:
        self.documents.append(document)


class DummyUpdate:
    def __init__(self) -> None:
        self.message = DummyMessage()


class DummyApplication:
    def __init__(self) -> None:
        self.bot_data: dict[str, object] = {}


class DummyContext:
    def __init__(self, args: list[str]) -> None:
        self.args = args
        self.application = DummyApplication()


def test_dlogs_page_buttons_include_tail() -> None:
    lines = [f"line {i}" for i in range(120)]
    msg, keyboard, _ = callbacks._render_logs_page("svc", lines, start=0)
    assert msg
    assert keyboard is not None
    buttons = [b for row in keyboard.inline_keyboard for b in row]
    tail_buttons = [b for b in buttons if b.text == "⬇️ Tail"]
    assert tail_buttons
    assert tail_buttons[0].callback_data == "dlogs:page:svc:70"


def test_dlogs_callback_parses_since() -> None:
    payload = "dlogs:page:my:container:10:1700000000"
    parsed = callbacks._parse_log_page_payload(payload, "dlogs:page:")
    assert parsed == ("my:container", 10, 1700000000)


@pytest.mark.asyncio
async def test_dlogs_default_file(monkeypatch) -> None:
    async def allow_guard(update, context) -> bool:
        return True

    async def fake_logs(state, container, refresh, since=None) -> list[str]:
        return ["line1", "line2"]

    monkeypatch.setattr(docker, "guard_sensitive", allow_guard)
    monkeypatch.setattr(docker, "_get_log_lines", fake_logs)
    update = DummyUpdate()
    context = DummyContext(args=["svc"])

    await docker.cmd_dlogs(update, context)

    assert update.message.documents
