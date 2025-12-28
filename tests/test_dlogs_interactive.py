import pytest
import io
from tele_home_supervisor.handlers import docker, callbacks
from tele_home_supervisor.handlers.common import get_state
from tele_home_supervisor.models.cache import CacheEntry
import time


class DummyMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []
        self.documents: list[object] = []
        self.reply_markup = None
        self.text = None

    async def reply_text(self, text: str, reply_markup=None, **_) -> None:
        self.replies.append(text)
        self.reply_markup = reply_markup
        self.text = text

    async def edit_message_text(self, text: str, reply_markup=None, **_) -> None:
        self.text = text
        self.reply_markup = reply_markup

    async def reply_document(self, document, **_) -> None:
        self.documents.append(document)


class DummyUpdate:
    def __init__(self) -> None:
        self.message = DummyMessage()
        self.callback_query = DummyCallbackQuery(self.message)
        self.effective_chat = DummyChat()
        self.effective_user = DummyUser()


class DummyCallbackQuery:
    def __init__(self, message) -> None:
        self.message = message
        self.data = ""
        self.id = "123"

    async def answer(self, text=None, **_) -> None:
        pass

    async def edit_message_text(self, text: str, reply_markup=None, **_) -> None:
        self.message.text = text
        self.message.reply_markup = reply_markup


class DummyChat:
    id = 12345


class DummyUser:
    id = 67890


class DummyContext:
    def __init__(self, args: list[str]) -> None:
        self.args = args
        self.application = DummyApplication()
        self.bot = DummyBot()


class DummyApplication:
    def __init__(self) -> None:
        self.bot_data: dict[str, object] = {}
        self.bot = DummyBot()


class DummyBot:
    async def send_message(self, chat_id, text, **_) -> None:
        pass


@pytest.mark.asyncio
async def test_dlogs_no_args_shows_menu(monkeypatch) -> None:
    async def allow_guard(update, context) -> bool:
        return True

    monkeypatch.setattr(docker, "guard_sensitive", allow_guard)

    update = DummyUpdate()
    context = DummyContext(args=[])
    state = get_state(context.application)
    state.caches["containers"] = CacheEntry(
        updated_at=time.monotonic(), items={"c1", "c2"}
    )

    await docker.cmd_dlogs(update, context)

    assert "Select a container" in update.message.replies[0]
    assert update.message.reply_markup is not None
    # Check buttons
    buttons = [b for row in update.message.reply_markup.inline_keyboard for b in row]
    assert any("c1" in b.text for b in buttons)


@pytest.mark.asyncio
async def test_dlogs_file_callback(monkeypatch) -> None:
    def allow_guard(update) -> bool:
        return True

    monkeypatch.setattr(callbacks, "allowed", allow_guard)

    async def mock_get_logs(container, since=None) -> str:
        return "log content line 1\nline 2"

    monkeypatch.setattr(callbacks.services, "get_container_logs_full", mock_get_logs)

    update = DummyUpdate()
    update.callback_query.data = "dlogs:file:c1:0"
    context = DummyContext(args=[])

    await callbacks.handle_callback_query(update, context)

    assert update.message.documents
    doc = update.message.documents[0]
    assert isinstance(doc, io.BytesIO)
    assert doc.getvalue() == b"log content line 1\nline 2"
    assert doc.name == "c1-logs.txt"


@pytest.mark.asyncio
async def test_dlogs_list_callback(monkeypatch) -> None:
    def allow_guard(update) -> bool:
        return True

    monkeypatch.setattr(callbacks, "allowed", allow_guard)

    update = DummyUpdate()
    update.callback_query.data = "dlogs:list:0"
    context = DummyContext(args=[])
    state = get_state(context.application)
    state.caches["containers"] = CacheEntry(
        updated_at=time.monotonic(), items={"c1", "c2"}
    )

    await callbacks.handle_callback_query(update, context)

    assert "Select a container" in update.message.text
    assert update.message.reply_markup is not None
