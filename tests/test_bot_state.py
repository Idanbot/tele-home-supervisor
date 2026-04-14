"""Tests for BotState model."""

import secrets
import tempfile
import time
from pathlib import Path

from tele_home_supervisor.models.bot_state import BotState
from tele_home_supervisor.models.audit import AuditEntry


class TestBotStateAuth:
    """Tests for auth grant functionality."""

    def test_grant_auth(self) -> None:
        state = BotState()
        expiry = time.time() + 3600
        state.grant_auth(123, expiry)
        assert 123 in state.auth_grants
        assert state.auth_grants[123] == expiry
        assert state.auth_records[123].expires_at == expiry

    def test_revoke_auth(self) -> None:
        state = BotState()
        state.auth_grants[123] = time.time() + 3600
        state.auth_records[123] = state.auth_record_for(123)
        state.revoke_auth(123)
        assert 123 not in state.auth_grants
        assert 123 not in state.auth_records

    def test_revoke_nonexistent(self) -> None:
        state = BotState()
        # Should not raise
        state.revoke_auth(999)

    def test_regrant_updates_existing_record(self) -> None:
        state = BotState()
        first_start = time.time()
        first_expiry = first_start + 3600
        state.grant_auth(123, first_expiry, granted_at=first_start, username="old")

        second_start = first_start + 120
        second_expiry = second_start + 3600
        state.grant_auth(123, second_expiry, granted_at=second_start, username="new")

        assert len(state.auth_records) == 1
        assert state.auth_records[123].granted_at == second_start
        assert state.auth_records[123].expires_at == second_expiry
        assert state.auth_records[123].username == "new"


class TestBotStateCache:
    """Tests for caching functionality."""

    def test_get_cached_returns_set(self) -> None:
        state = BotState()
        # get_cached returns a set from CacheEntry.items
        result = state.get_cached("containers")
        assert isinstance(result, set)

    def test_cache_miss_returns_empty_set(self) -> None:
        state = BotState()
        result = state.get_cached("nonexistent")
        assert result == set()


class TestBotStateTorrentSubscriptions:
    """Tests for torrent completion subscription."""

    def test_set_subscription(self) -> None:
        state = BotState()
        # set_torrent_completion_subscription(chat_id, enable)
        result = state.set_torrent_completion_subscription(123, True)
        assert result is True
        assert 123 in state.torrent_completion_subscribers
        # Disable
        result = state.set_torrent_completion_subscription(123, False)
        assert result is False
        assert 123 not in state.torrent_completion_subscribers

    def test_toggle_subscription(self) -> None:
        state = BotState()
        # None means toggle
        result = state.set_torrent_completion_subscription(123, None)
        assert result is True
        assert 123 in state.torrent_completion_subscribers
        result = state.set_torrent_completion_subscription(123, None)
        assert result is False
        assert 123 not in state.torrent_completion_subscribers

    def test_torrent_completion_enabled(self) -> None:
        state = BotState()
        assert state.torrent_completion_enabled(123) is False
        state.torrent_completion_subscribers.add(123)
        assert state.torrent_completion_enabled(123) is True


class TestBotStateNotificationMutes:
    """Tests for notification mute functionality."""

    def test_toggle_gameoffers_mute(self) -> None:
        state = BotState()
        # First toggle mutes
        assert state.toggle_gameoffers_mute(123) is True
        assert state.is_gameoffers_muted(123) is True
        # Second toggle unmutes
        assert state.toggle_gameoffers_mute(123) is False
        assert state.is_gameoffers_muted(123) is False

    def test_toggle_hackernews_mute(self) -> None:
        state = BotState()
        # First toggle mutes
        assert state.toggle_hackernews_mute(123) is True
        assert state.is_hackernews_muted(123) is True
        # Second toggle unmutes
        assert state.toggle_hackernews_mute(123) is False
        assert state.is_hackernews_muted(123) is False


class TestBotStateMetrics:
    """Tests for command metrics tracking."""

    def test_record_command_success(self) -> None:
        state = BotState()
        # record_command(name, latency_s, ok, error_msg)
        state.record_command("test", 0.1, ok=True, error_msg=None)
        metrics = state.command_metrics["test"]
        assert metrics.count == 1
        assert metrics.success == 1
        assert metrics.error == 0

    def test_record_command_error(self) -> None:
        state = BotState()
        state.record_command("test", 0.1, ok=False, error_msg="boom")
        metrics = state.command_metrics["test"]
        assert metrics.count == 1
        assert metrics.success == 0
        assert metrics.error == 1
        assert metrics.last_error == "boom"

    def test_record_rate_limited(self) -> None:
        state = BotState()
        state.record_rate_limited("test")
        metrics = state.command_metrics["test"]
        assert metrics.rate_limited == 1
        assert metrics.count == 0


class TestBotStatePersistence:
    """Tests for state persistence."""

    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            state = BotState()
            state._state_file = state_file

            state.gameoffers_muted.add(123)
            state.hackernews_muted.add(456)
            state.disabled_intel_modules[123] = {"weather", "news"}
            state.torrent_completion_subscribers.add(789)
            state.grant_auth(100, time.time() + 3600)

            # Save
            state.save()

            # Create new state and load
            state2 = BotState()
            state2._state_file = state_file
            state2.load_state()

            # Verify
            assert 123 in state2.gameoffers_muted
            assert 456 in state2.hackernews_muted
            assert state2.disabled_intel_modules[123] == {"weather", "news"}
            assert 789 in state2.torrent_completion_subscribers

            assert 100 in state2.auth_grants
            assert 100 in state2.auth_records

    def test_load_nonexistent_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = BotState()
            state._state_file = Path(tmpdir) / "nonexistent.json"
            # Should not raise
            state.load_state()

    def test_load_only_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            state = BotState()
            state._state_file = state_file

            state.gameoffers_muted.add(123)
            state.save()
            state.load_state()

            # Modify after load
            state.gameoffers_muted.add(456)

            # Second load should be no-op
            state.load_state()
            assert 456 in state.gameoffers_muted


class TestBotStateMagnetCache:
    """Tests for magnet link caching."""

    def test_store_and_get_magnet(self) -> None:
        state = BotState()
        # store_magnet(name, magnet, seeders=0, leechers=0) returns key
        key = state.store_magnet("Ubuntu ISO", "magnet:?xt=...", 1024, 10)
        result = state.get_magnet(key)
        assert result is not None
        # Returns (name, magnet, seeders, leechers)
        assert result[0] == "Ubuntu ISO"
        assert result[1] == "magnet:?xt=..."

    def test_get_nonexistent_magnet(self) -> None:
        state = BotState()
        result = state.get_magnet("nonexistent")
        assert result is None


class TestBotStateAlerts:
    """Tests for alert functionality."""

    def test_alerts_enabled_toggle(self) -> None:
        state = BotState()
        assert state.alerts_enabled_for(123) is False
        state.set_alerts_enabled(123, True)
        assert state.alerts_enabled_for(123) is True
        state.set_alerts_enabled(123, False)
        assert state.alerts_enabled_for(123) is False

    def test_add_alert_rule(self) -> None:
        state = BotState()
        # add_alert_rule returns AlertRule object
        rule = state.add_alert_rule(
            chat_id=123,
            metric="disk_used",
            operator=">",
            threshold=90.0,
            duration_s=300,
        )
        assert rule is not None
        assert rule.id is not None
        fetched = state.get_alert_rule(rule.id)
        assert fetched is not None
        assert fetched.metric == "disk_used"
        assert fetched.threshold == 90.0

    def test_remove_alert_rule(self) -> None:
        state = BotState()
        rule = state.add_alert_rule(
            chat_id=123,
            metric="disk_used",
            operator=">",
            threshold=90.0,
            duration_s=300,
        )
        # remove_alert_rule(chat_id, rule_id)
        state.remove_alert_rule(123, rule.id)
        assert state.get_alert_rule(rule.id) is None

    def test_alert_rules_for_chat(self) -> None:
        state = BotState()
        state.add_alert_rule(123, "disk_used", ">", 90.0, 300)
        state.add_alert_rule(123, "load", ">", 2.0, 300)
        state.add_alert_rule(456, "mem_used", ">", 80.0, 300)

        rules = state.alert_rules_for_chat(123)
        assert len(rules) == 2


class TestBotStateAudit:
    """Tests for audit log functionality."""

    def test_record_audit_entry(self) -> None:
        state = BotState()
        entry = AuditEntry(
            id=secrets.token_hex(4),
            chat_id=123,
            user_id=456,
            user_name="testuser",
            action="docker",
            target="nginx",
            status="ok",
            duration_ms=100,
            created_at=time.time(),
        )
        state.record_audit_entry(entry)
        entries = state.get_audit_entries(123, limit=10)
        assert len(entries) == 1
        assert entries[0].action == "docker"
        assert entries[0].user_name == "testuser"

    def test_audit_log_limit(self) -> None:
        state = BotState()
        # Add more than the limit
        for i in range(250):
            entry = AuditEntry(
                id=secrets.token_hex(4),
                chat_id=123,
                user_id=456,
                user_name="testuser",
                action=f"cmd{i}",
                target=None,
                status="ok",
                duration_ms=10,
                created_at=time.time(),
            )
            state.record_audit_entry(entry)
        # Should be capped at max
        entries = state.get_audit_entries(123, limit=300)
        assert len(entries) <= 200

    def test_clear_audit_entries(self) -> None:
        state = BotState()
        entry = AuditEntry(
            id=secrets.token_hex(4),
            chat_id=123,
            user_id=456,
            user_name="user",
            action="cmd",
            target=None,
            status="ok",
            duration_ms=10,
            created_at=time.time(),
        )
        state.record_audit_entry(entry)
        state.clear_audit_entries(123)
        entries = state.get_audit_entries(123, limit=10)
        assert len(entries) == 0
