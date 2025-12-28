import pytest
from unittest.mock import MagicMock
from tele_home_supervisor.handlers import torrents, callbacks
from tele_home_supervisor.handlers.common import get_state
from tele_home_supervisor import services


class DummyMessage:
    def __init__(self, chat_id=12345) -> None:
        self.chat = MagicMock()
        self.chat.id = chat_id
        self.replies: list[str] = []
        self.reply_markup = None
        self.text = None

    async def reply_text(self, text: str, reply_markup=None, **_) -> None:
        self.replies.append(text)
        self.reply_markup = reply_markup
        self.text = text

    async def edit_message_text(self, text: str, reply_markup=None, **_) -> None:
        self.text = text
        self.reply_markup = reply_markup


class DummyUpdate:
    def __init__(self, chat_id=12345) -> None:
        self.effective_chat = MagicMock()
        self.effective_chat.id = chat_id
        self.message = DummyMessage(chat_id)
        self.callback_query = DummyCallbackQuery(self.message)


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


class DummyApplication:
    def __init__(self) -> None:
        self.bot_data: dict[str, object] = {}


class DummyContext:
    def __init__(self, args: list[str] = None) -> None:
        self.args = args or []
        self.application = DummyApplication()


@pytest.mark.asyncio
async def test_torrent_add_subscribes(monkeypatch):
    # Mock guard_sensitive to allow
    async def allow_guard(update, context):
        return True

    monkeypatch.setattr(torrents, "guard_sensitive", allow_guard)

    # Mock services.torrent_add
    async def mock_add(magnet, save_path="/downloads"):
        return "Torrent added"

    monkeypatch.setattr(services, "torrent_add", mock_add)

    update = DummyUpdate(chat_id=999)
    context = DummyContext(args=["magnet:?xt=..."])
    state = get_state(context.application)

    # Ensure not subscribed initially
    state.set_torrent_completion_subscription(999, False)
    assert not state.torrent_completion_enabled(999)

    await torrents.cmd_torrent_add(update, context)

    # Check response
    assert "Torrent added" in update.message.replies[0]
    # Should NOT have the notification text anymore
    assert "Subscribed to completion notifications" not in update.message.replies[0]
    # But should be subscribed in state
    assert state.torrent_completion_enabled(999)


@pytest.mark.asyncio
async def test_pb_add_callback_subscribes(monkeypatch):
    # Mock allowed
    def allow_guard(update):
        return True

    monkeypatch.setattr(callbacks, "allowed", allow_guard)

    # Mock services.torrent_add
    async def mock_add(magnet, save_path="/downloads"):
        return "Torrent added"

    monkeypatch.setattr(services, "torrent_add", mock_add)

    # Setup state with a magnet
    update = DummyUpdate(chat_id=888)
    context = DummyContext()
    state = get_state(context.application)
    key = state.store_magnet("Test Torrent", "magnet:?xt=...", seeders=10, leechers=2)

    update.callback_query.data = f"pbadd:{key}"

    # Ensure not subscribed initially
    state.set_torrent_completion_subscription(888, False)
    assert not state.torrent_completion_enabled(888)

    await callbacks.handle_callback_query(update, context)

    # Check response
    assert "Torrent added" in update.message.replies[0]
    assert "Subscribed to completion notifications" not in update.message.replies[0]
    assert state.torrent_completion_enabled(888)


@pytest.mark.asyncio
async def test_pbsearch_results_and_select(monkeypatch):
    # Mock guard_sensitive
    async def allow_guard(update, context):
        return True

    monkeypatch.setattr(torrents, "guard_sensitive", allow_guard)
    monkeypatch.setattr(callbacks, "allowed", lambda u: True)

    # Mock services.piratebay_search
    async def mock_search(query, debug_sink=None):
        return [
            {"name": "Result 1", "seeders": 100, "leechers": 10, "magnet": "magnet1"},
            {"name": "Result 2", "seeders": 50, "leechers": 5, "magnet": "magnet2"},
        ]

    monkeypatch.setattr(services, "piratebay_search", mock_search)

    # Test /pbsearch
    update = DummyUpdate()
    context = DummyContext(args=["ubuntu"])
    await torrents.cmd_pbsearch(update, context)

    assert "Pirate Bay Search: ubuntu" in update.message.replies[0]
    assert update.message.reply_markup is not None

    # Check buttons use pbselect
    buttons = [b for row in update.message.reply_markup.inline_keyboard for b in row]
    assert len(buttons) == 2
    assert "Result 1" in buttons[0].text
    assert buttons[0].callback_data.startswith("pbselect:")

    # Extract key and test select callback
    key = buttons[0].callback_data.split(":")[1]

    # Update for callback
    update_cb = DummyUpdate()
    update_cb.callback_query.data = f"pbselect:{key}"
    context_cb = DummyContext()
    # Share state application
    context_cb.application = context.application

    await callbacks.handle_callback_query(update_cb, context_cb)

    assert "Result 1" in update_cb.message.replies[0]
    assert "Seeds: 100" in update_cb.message.replies[0]
    assert "Leechers: 10" in update_cb.message.replies[0]

    # Check action buttons
    cb_buttons = [
        b for row in update_cb.message.reply_markup.inline_keyboard for b in row
    ]
    assert any("Get Magnet" in b.text for b in cb_buttons)
    assert any("Add to qBittorrent" in b.text for b in cb_buttons)
    assert any(b.callback_data == f"pbmagnet:{key}" for b in cb_buttons)
    assert any(b.callback_data == f"pbadd:{key}" for b in cb_buttons)
