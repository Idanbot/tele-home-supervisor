"""Tests for media message tracking and auto-deletion."""

from __future__ import annotations

import time

import pytest

from tele_home_supervisor.models.bot_state import BotState
from tele_home_supervisor.models import persistence


# ---------------------------------------------------------------------------
# BotState tracking
# ---------------------------------------------------------------------------


class TestMediaTracking:
    """Tests for BotState media message tracking methods."""

    def test_track_media_message_appends(self):
        state = BotState()
        state.track_media_message(111, 1)
        state.track_media_message(111, 2)
        assert len(state.media_messages) == 2
        assert state.media_messages[0][:2] == [111, 1]
        assert state.media_messages[1][:2] == [111, 2]

    def test_track_media_message_records_timestamp(self):
        state = BotState()
        before = time.time()
        state.track_media_message(123, 42)
        after = time.time()
        ts = state.media_messages[0][2]
        assert before <= ts <= after

    def test_pop_expired_media_empty(self):
        state = BotState()
        assert state.pop_expired_media(3600) == []

    def test_pop_expired_media_nothing_expired(self):
        state = BotState()
        state.track_media_message(1, 10)
        assert state.pop_expired_media(3600) == []
        assert len(state.media_messages) == 1

    def test_pop_expired_media_returns_old_entries(self):
        state = BotState()
        # Manually insert an old entry
        state.media_messages.append([100, 200, time.time() - 7200])
        state.track_media_message(100, 300)  # fresh

        expired = state.pop_expired_media(3600)
        assert expired == [(100, 200)]
        assert len(state.media_messages) == 1
        assert state.media_messages[0][1] == 300

    def test_pop_all_media_returns_all(self):
        state = BotState()
        state.track_media_message(1, 10)
        state.track_media_message(2, 20)

        result = state.pop_all_media()
        assert result == [(1, 10), (2, 20)]
        assert state.media_messages == []

    def test_pop_all_media_empty(self):
        state = BotState()
        assert state.pop_all_media() == []


# ---------------------------------------------------------------------------
# Persistence round-trip
# ---------------------------------------------------------------------------


class TestMediaPersistence:
    """Tests for media message serialization/deserialization."""

    def test_serialize_includes_media_messages(self):
        state = BotState()
        state.track_media_message(111, 42)
        data = persistence.serialize(state)
        assert "media_messages" in data
        assert len(data["media_messages"]) == 1
        assert data["media_messages"][0][:2] == [111, 42]

    def test_load_media_messages_roundtrip(self, tmp_path):
        state = BotState()
        state._state_file = tmp_path / "state.json"
        state.track_media_message(100, 200)
        state.track_media_message(300, 400)
        state.save()

        state2 = BotState()
        state2._state_file = tmp_path / "state.json"
        persistence.load(state2, state2._state_file)
        assert len(state2.media_messages) == 2
        assert state2.media_messages[0][:2] == [100, 200]
        assert state2.media_messages[1][:2] == [300, 400]

    def test_load_media_messages_skips_malformed(self):
        from tele_home_supervisor.models.persistence import _load_media_messages

        result = _load_media_messages(
            [
                [1, 2, 3.0],  # valid
                "bad",  # not a list
                [1, 2],  # too short
                [1, "x", 3.0],  # bad message_id
                [1, 2, "bad_ts"],  # bad timestamp
            ]
        )
        assert len(result) == 1
        assert result[0] == [1, 2, 3.0]


# ---------------------------------------------------------------------------
# tracked_reply_photo helper
# ---------------------------------------------------------------------------


class TestTrackedReplyPhoto:
    """Tests for the tracked_reply_photo wrapper."""

    @pytest.mark.asyncio
    async def test_tracked_reply_photo_records_message(self):
        from tele_home_supervisor.handlers.common import tracked_reply_photo

        state = BotState()

        class FakeChat:
            id = 999

        class FakeMessage:
            message_id = 42
            chat = FakeChat()

        class FakeSender:
            async def reply_photo(self, **kwargs):
                return FakeMessage()

        sender = FakeSender()
        result = await tracked_reply_photo(sender, state, photo="url")
        assert result.message_id == 42
        assert len(state.media_messages) == 1
        assert state.media_messages[0][:2] == [999, 42]

    @pytest.mark.asyncio
    async def test_tracked_send_photo_records_message(self):
        from tele_home_supervisor.handlers.common import tracked_send_photo

        state = BotState()

        class FakeChat:
            id = 555

        class FakeMessage:
            message_id = 77
            chat = FakeChat()

        class FakeBot:
            async def send_photo(self, **kwargs):
                return FakeMessage()

        bot = FakeBot()
        result = await tracked_send_photo(bot, state, chat_id=555, photo="url")
        assert result.message_id == 77
        assert len(state.media_messages) == 1
        assert state.media_messages[0][:2] == [555, 77]


# ---------------------------------------------------------------------------
# Background delete_media_messages
# ---------------------------------------------------------------------------


class TestDeleteMediaMessages:
    """Tests for the background delete_media_messages function."""

    @pytest.mark.asyncio
    async def test_delete_media_messages_success(self):
        from tele_home_supervisor.background import delete_media_messages

        deleted_calls: list[tuple[int, int]] = []

        class FakeBot:
            async def delete_message(self, chat_id, message_id):
                deleted_calls.append((chat_id, message_id))

        class FakeApp:
            bot = FakeBot()

        count = await delete_media_messages(FakeApp(), [(1, 10), (2, 20)])
        assert count == 2
        assert deleted_calls == [(1, 10), (2, 20)]

    @pytest.mark.asyncio
    async def test_delete_media_messages_partial_failure(self):
        from tele_home_supervisor.background import delete_media_messages

        class FakeBot:
            async def delete_message(self, chat_id, message_id):
                if message_id == 10:
                    raise Exception("not found")

        class FakeApp:
            bot = FakeBot()

        count = await delete_media_messages(FakeApp(), [(1, 10), (2, 20)])
        assert count == 1  # only second succeeded

    @pytest.mark.asyncio
    async def test_delete_media_messages_empty(self):
        from tele_home_supervisor.background import delete_media_messages

        class FakeApp:
            bot = None

        count = await delete_media_messages(FakeApp(), [])
        assert count == 0
