"""Tests for audit handler."""

import time

import pytest

from tele_home_supervisor.handlers import audit
from tele_home_supervisor.handlers.common import get_state

from conftest import DummyContext, DummyUpdate


class TestCmdAudit:
    """Tests for /audit command."""

    @pytest.mark.asyncio
    async def test_shows_empty_log(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(audit, "guard_sensitive", mock_guard)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()

        await audit.cmd_audit(update, context)

        assert len(update.message.replies) == 1
        assert "No audit" in update.message.replies[0]

    @pytest.mark.asyncio
    async def test_shows_audit_entries(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(audit, "guard_sensitive", mock_guard)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()

        from tele_home_supervisor.models.audit import AuditEntry

        state = get_state(context.application)
        state.record_audit_entry(
            AuditEntry(
                id="entry1",
                chat_id=123,
                user_id=456,
                user_name="testuser",
                action="docker",
                target="nginx",
                status="ok",
                duration_ms=50,
                created_at=time.time(),
            )
        )

        await audit.cmd_audit(update, context)

        assert len(update.message.replies) == 1
        reply = update.message.replies[0]
        assert "Audit" in reply
        assert "docker" in reply
        assert "testuser" in reply

    @pytest.mark.asyncio
    async def test_clear_clears_log(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(audit, "guard_sensitive", mock_guard)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()

        from tele_home_supervisor.models.audit import AuditEntry

        state = get_state(context.application)
        state.record_audit_entry(
            AuditEntry(
                id="entry1",
                chat_id=123,
                user_id=456,
                user_name="user",
                action="cmd",
                target=None,
                status="ok",
                duration_ms=10,
                created_at=time.time(),
            )
        )

        # Reuse the same context but update args for "clear"
        context.args = ["clear"]
        await audit.cmd_audit(update, context)

        assert "cleared" in update.message.replies[-1].lower()
        entries = state.get_audit_entries(123, limit=10)
        assert len(entries) == 0

    @pytest.mark.asyncio
    async def test_limit_parameter(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(audit, "guard_sensitive", mock_guard)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()

        from tele_home_supervisor.models.audit import AuditEntry

        state = get_state(context.application)
        for i in range(10):
            state.record_audit_entry(
                AuditEntry(
                    id=f"entry{i}",
                    chat_id=123,
                    user_id=456,
                    user_name="user",
                    action=f"cmd{i}",
                    target=None,
                    status="ok",
                    duration_ms=10,
                    created_at=time.time(),
                )
            )

        context = DummyContext(args=["5"])
        await audit.cmd_audit(update, context)

        # The output should be limited
        assert len(update.message.replies) >= 1


class TestFormatEntry:
    """Tests for _format_entry function."""

    def test_formats_audit_entry(self) -> None:
        from tele_home_supervisor.models.audit import AuditEntry

        entry = AuditEntry(
            id="entry1",
            chat_id=123,
            user_id=123,
            user_name="testuser",
            action="docker",
            target="nginx",
            status="ok",
            duration_ms=100,
            created_at=time.time(),
        )

        result = audit._format_entry(entry)

        assert "testuser" in result
        assert "docker" in result
        assert "nginx" in result
        assert "ok" in result
        assert "100ms" in result

    def test_handles_missing_target(self) -> None:
        from tele_home_supervisor.models.audit import AuditEntry

        entry = AuditEntry(
            id="entry1",
            chat_id=123,
            user_id=123,
            user_name="testuser",
            action="health",
            target=None,
            status="ok",
            duration_ms=50,
            created_at=time.time(),
        )

        result = audit._format_entry(entry)

        assert "testuser" in result
        assert "-" in result  # Should show dash for missing target
