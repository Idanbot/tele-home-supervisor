"""Tests for alerts handler."""

import pytest

from tele_home_supervisor.handlers import alerts
from tele_home_supervisor.handlers.common import get_state

from conftest import DummyContext, DummyUpdate


class TestCmdAlerts:
    """Tests for /alerts command."""

    @pytest.mark.asyncio
    async def test_shows_status_by_default(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(alerts, "guard_sensitive", mock_guard)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()

        await alerts.cmd_alerts(update, context)

        assert len(update.message.replies) == 1
        reply = update.message.replies[0]
        assert "Alerts" in reply

    @pytest.mark.asyncio
    async def test_alerts_on_enables(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(alerts, "guard_sensitive", mock_guard)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext(args=["on"])

        await alerts.cmd_alerts(update, context)

        state = get_state(context.application)
        assert state.alerts_enabled_for(123) is True

    @pytest.mark.asyncio
    async def test_alerts_off_disables(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(alerts, "guard_sensitive", mock_guard)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext(args=["on"])
        await alerts.cmd_alerts(update, context)

        context = DummyContext(args=["off"])
        await alerts.cmd_alerts(update, context)

        state = get_state(context.application)
        assert state.alerts_enabled_for(123) is False

    @pytest.mark.asyncio
    async def test_alerts_add_creates_rule(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(alerts, "guard_sensitive", mock_guard)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext(args=["add", "disk_used", ">", "90"])

        await alerts.cmd_alerts(update, context)

        state = get_state(context.application)
        rules = state.alert_rules_for_chat(123)
        assert len(rules) >= 1

    @pytest.mark.asyncio
    async def test_alerts_add_invalid_metric(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(alerts, "guard_sensitive", mock_guard)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext(args=["add", "invalid_metric", ">", "90"])

        await alerts.cmd_alerts(update, context)

        # Should show error about invalid metric
        assert (
            "metric" in update.message.replies[0].lower()
            or "invalid" in update.message.replies[0].lower()
        )


class TestRenderAlertRules:
    """Tests for _render_alert_rules function."""

    def test_formats_rules(self) -> None:
        from tele_home_supervisor.models.alerts import AlertRule

        rules = [
            AlertRule(
                id="rule1",
                chat_id=123,
                metric="disk_used",
                operator=">",
                threshold=90.0,
                duration_s=300,
            )
        ]
        lines = alerts._render_alert_rules(rules)
        assert len(lines) == 1
        assert "disk_used" in lines[0]
        assert "90" in lines[0]


class TestBuildAlertsKeyboard:
    """Tests for build_alerts_keyboard function."""

    def test_returns_none_for_empty(self) -> None:
        result = alerts.build_alerts_keyboard([])
        assert result is None

    def test_returns_keyboard_for_rules(self) -> None:
        from tele_home_supervisor.models.alerts import AlertRule

        rules = [
            AlertRule(
                id="rule1",
                chat_id=123,
                metric="disk_used",
                operator=">",
                threshold=90.0,
                duration_s=300,
            )
        ]
        result = alerts.build_alerts_keyboard(rules)
        assert result is not None


class TestRenderAlertsOverview:
    """Tests for render_alerts_overview function."""

    def test_shows_enabled_status(self) -> None:
        from tele_home_supervisor.models.bot_state import BotState

        state = BotState()
        state.set_alerts_enabled(123, True)

        text, keyboard = alerts.render_alerts_overview(state, 123)

        assert "ON" in text

    def test_shows_disabled_status(self) -> None:
        from tele_home_supervisor.models.bot_state import BotState

        state = BotState()
        state.set_alerts_enabled(123, False)

        text, keyboard = alerts.render_alerts_overview(state, 123)

        assert "OFF" in text
