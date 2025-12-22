import time

import pytest

from tele_home_supervisor import config
from tele_home_supervisor.handlers import meta
from tele_home_supervisor.handlers.common import get_state


class DummyChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id
        self.sent: list[str] = []

    async def send_message(self, text: str) -> None:
        self.sent.append(text)


class DummyUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


class DummyMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, **_) -> None:
        self.replies.append(text)


class DummyUpdate:
    def __init__(self, chat_id: int, user_id: int) -> None:
        self.effective_chat = DummyChat(chat_id)
        self.effective_user = DummyUser(user_id)
        self.message = DummyMessage()


class DummyApplication:
    def __init__(self) -> None:
        self.bot_data: dict[str, object] = {}


class DummyContext:
    def __init__(self, args: list[str]) -> None:
        self.args = args
        self.application = DummyApplication()


@pytest.mark.asyncio
async def test_cmd_auth_requires_totp_secret(monkeypatch) -> None:
    monkeypatch.setattr(config, "ALLOWED", {123})
    monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", None)
    update = DummyUpdate(chat_id=123, user_id=123)
    context = DummyContext(args=["123456"])

    await meta.cmd_auth(update, context)

    assert update.message.replies == ["⛔ BOT_AUTH_TOTP_SECRET is not configured."]


@pytest.mark.asyncio
async def test_cmd_auth_requires_args(monkeypatch) -> None:
    monkeypatch.setattr(config, "ALLOWED", {123})
    monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", "BASE32")
    update = DummyUpdate(chat_id=123, user_id=123)
    context = DummyContext(args=[])

    await meta.cmd_auth(update, context)

    assert update.message.replies == ["Usage: /auth <code>"]


@pytest.mark.asyncio
async def test_cmd_auth_rejects_non_digit_codes(monkeypatch) -> None:
    monkeypatch.setattr(config, "ALLOWED", {123})
    monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", "BASE32")
    update = DummyUpdate(chat_id=123, user_id=123)
    context = DummyContext(args=["12ab"])

    await meta.cmd_auth(update, context)

    assert update.message.replies == ["❌ Invalid auth code."]


@pytest.mark.asyncio
async def test_cmd_auth_rejects_invalid_code(monkeypatch) -> None:
    monkeypatch.setattr(config, "ALLOWED", {123})
    monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", "BASE32")

    class DummyTotp:
        def __init__(self, secret: str) -> None:
            self.secret = secret

        def verify(self, otp: str, valid_window: int = 0) -> bool:
            return False

    monkeypatch.setattr(meta.pyotp, "TOTP", DummyTotp)
    update = DummyUpdate(chat_id=123, user_id=123)
    context = DummyContext(args=["123-456"])

    await meta.cmd_auth(update, context)

    assert update.message.replies == ["❌ Invalid auth code."]
    state = get_state(context.application)
    assert update.effective_user.id not in state.auth_grants


@pytest.mark.asyncio
async def test_cmd_auth_accepts_valid_code(monkeypatch) -> None:
    monkeypatch.setattr(config, "ALLOWED", {123})
    monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", "BASE32")

    class DummyTotp:
        def __init__(self, secret: str) -> None:
            self.secret = secret

        def verify(self, otp: str, valid_window: int = 0) -> bool:
            return otp == "123456" and self.secret == "BASE32"

    monkeypatch.setattr(meta.pyotp, "TOTP", DummyTotp)
    update = DummyUpdate(chat_id=123, user_id=123)
    context = DummyContext(args=["123456"])

    await meta.cmd_auth(update, context)

    assert update.message.replies == ["✅ Authorized for 24 hours."]
    state = get_state(context.application)
    expiry = state.auth_grants.get(update.effective_user.id)
    assert expiry is not None
    assert expiry > time.monotonic()
