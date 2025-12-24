"""Shared test fixtures and dummy classes."""

from __future__ import annotations

from typing import Any


class DummyChat:
    """Dummy Telegram chat for testing."""

    def __init__(self, chat_id: int) -> None:
        self.id = chat_id
        self.sent: list[str] = []

    async def send_message(self, text: str) -> None:
        self.sent.append(text)


class DummyUser:
    """Dummy Telegram user for testing."""

    def __init__(self, user_id: int, username: str | None = None) -> None:
        self.id = user_id
        self.username = username


class DummyMessage:
    """Dummy Telegram message for testing."""

    def __init__(self) -> None:
        self.replies: list[str] = []
        self.photos: list[tuple[str, str]] = []  # (photo_url, caption)

    async def reply_text(self, text: str, **_: Any) -> None:
        self.replies.append(text)

    async def reply_photo(self, photo: str, caption: str = "", **_: Any) -> None:
        self.photos.append((photo, caption))


class DummyUpdate:
    """Dummy Telegram update for testing."""

    def __init__(self, chat_id: int, user_id: int) -> None:
        self.effective_chat = DummyChat(chat_id)
        self.effective_user = DummyUser(user_id)
        self.message = DummyMessage()


class DummyApplication:
    """Dummy Telegram application for testing."""

    def __init__(self) -> None:
        self.bot_data: dict[str, object] = {}


class DummyContext:
    """Dummy Telegram context for testing."""

    def __init__(self, args: list[str] | None = None) -> None:
        self.args = args or []
        self.application = DummyApplication()


class DummyResponse:
    """Dummy HTTP response for testing."""

    def __init__(self, data: object, status: int = 200, text: str = "") -> None:
        self._data = data
        self.status_code = status
        self.text = text or str(data)
        self.ok = 200 <= status < 300

    def json(self) -> object:
        return self._data
