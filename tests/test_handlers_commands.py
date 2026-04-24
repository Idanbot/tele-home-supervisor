"""Tests for handler commands - system, docker, network."""

import pytest
from unittest.mock import AsyncMock, patch

from tele_home_supervisor import config
from tele_home_supervisor.handlers import system, docker, network
from tele_home_supervisor.models.managed_host import ManagedHost

from conftest import DummyContext, DummyUpdate


class TestSystemHandlers:
    """Tests for system command handlers."""

    @pytest.mark.asyncio
    async def test_cmd_ip_requires_auth(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", "SECRET")

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()

        await system.cmd_ip(update, context)

        # Should be blocked by guard_sensitive (no auth)
        assert len(update.effective_chat.sent) >= 1
        assert (
            "auth" in update.effective_chat.sent[0].lower()
            or "🔒" in update.effective_chat.sent[0]
        )

    @pytest.mark.asyncio
    async def test_cmd_diskusage_renders_output(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(system, "guard_sensitive", mock_guard)

        disk_stats = [
            {
                "path": "/",
                "percent": 50.0,
                "used": 100_000_000_000,
                "total": 200_000_000_000,
            },
            {
                "path": "/home",
                "percent": 25.0,
                "used": 50_000_000_000,
                "total": 200_000_000_000,
            },
        ]

        with patch(
            "tele_home_supervisor.services.utils.get_disk_usage_stats",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = disk_stats
            update = DummyUpdate(chat_id=123, user_id=123)
            context = DummyContext()

            await system.cmd_diskusage(update, context)

            assert len(update.message.replies) == 1
            reply = update.message.replies[0]
            assert "Disk Usage" in reply
            assert "/" in reply
            assert "50.0%" in reply

    @pytest.mark.asyncio
    async def test_cmd_remind_requires_args(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(system, "guard_sensitive", mock_guard)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext(args=[])

        await system.cmd_remind(update, context)

        assert "Usage" in update.message.replies[0]

    @pytest.mark.asyncio
    async def test_cmd_remind_invalid_duration(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(system, "guard_sensitive", mock_guard)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext(args=["abc", "reminder text"])

        await system.cmd_remind(update, context)

        assert "Invalid" in update.message.replies[0]

    @pytest.mark.asyncio
    async def test_cmd_ping_requires_args(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(system, "guard_sensitive", mock_guard)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext(args=[])

        await system.cmd_ping(update, context)

        assert "Usage" in update.message.replies[0]


class TestDockerHandlers:
    """Tests for docker command handlers."""

    @pytest.mark.asyncio
    async def test_cmd_docker_lists_containers(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(docker, "guard_sensitive", mock_guard)

        containers = [
            {
                "name": "nginx",
                "status": "running",
                "ports": "80/tcp",
                "image": "nginx:latest",
            },
            {
                "name": "redis",
                "status": "running",
                "ports": "6379/tcp",
                "image": "redis:7",
            },
        ]

        with patch(
            "tele_home_supervisor.services.list_containers", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = containers
            update = DummyUpdate(chat_id=123, user_id=123)
            context = DummyContext()

            await docker.cmd_docker(update, context)

            assert len(update.message.replies) >= 1
            reply = update.message.replies[0]
            assert "nginx" in reply or "Containers" in reply

    @pytest.mark.asyncio
    async def test_cmd_dlogs_requires_container_arg(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(docker, "guard_sensitive", mock_guard)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext(args=[])

        await docker.cmd_dlogs(update, context)

        assert len(update.message.replies) == 1
        assert (
            "Usage" in update.message.replies[0]
            or "container" in update.message.replies[0].lower()
        )


class TestNetworkHandlers:
    """Tests for network command handlers."""

    @pytest.mark.asyncio
    async def test_cmd_dns_requires_args(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(network, "guard_sensitive", mock_guard)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext(args=[])

        await network.cmd_dns(update, context)

        assert "Usage" in update.message.replies[0]

    @pytest.mark.asyncio
    async def test_cmd_dns_performs_lookup(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(network, "guard_sensitive", mock_guard)

        with patch(
            "tele_home_supervisor.services.utils.dns_lookup", new_callable=AsyncMock
        ) as mock:
            mock.return_value = "1.2.3.4"
            update = DummyUpdate(chat_id=123, user_id=123)
            context = DummyContext(args=["example.com"])

            await network.cmd_dns(update, context)

            assert len(update.message.replies) == 1
            assert "DNS" in update.message.replies[0]

    @pytest.mark.asyncio
    async def test_cmd_wifiqr_requires_args(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(network, "guard_sensitive", mock_guard)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext(args=[])

        await network.cmd_wifiqr(update, context)

        assert "Usage" in update.message.replies[0]

    @pytest.mark.asyncio
    async def test_cmd_wol_uses_configured_default_target(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        scheduled: list[tuple[str, bool]] = []
        packets: list[tuple[str, list[str], int]] = []

        def fake_schedule(context, *, chat_id: int, host: str, online: bool) -> None:
            scheduled.append((host, online))

        def fake_send(mac: str, *, broadcast_ips: list[str], port: int) -> None:
            packets.append((mac, broadcast_ips, port))

        monkeypatch.setattr(network, "guard_sensitive", mock_guard)
        monkeypatch.setattr(
            config,
            "default_managed_host",
            lambda: ManagedHost(
                name="gaming-pc",
                ping_host="192.168.1.10",
                mac="aa:bb:cc:dd:ee:ff",
                wol_broadcast_ip="192.168.1.255",
                wol_port=9,
            ),
        )
        monkeypatch.setattr(config, "get_managed_host", lambda value: None)
        monkeypatch.setattr(network, "_send_wol_packet", fake_send)
        monkeypatch.setattr(network, "_schedule_power_state_watch", fake_schedule)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext(args=[])

        await network.cmd_wol(update, context)

        assert packets == [
            ("aa:bb:cc:dd:ee:ff", ["192.168.1.255", "255.255.255.255"], 9)
        ]
        assert scheduled == [("192.168.1.10", True)]
        assert "Sent WOL Magic Packet" in update.message.replies[-1]

    @pytest.mark.asyncio
    async def test_cmd_wol_rejects_ip_without_mac(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(network, "guard_sensitive", mock_guard)
        monkeypatch.setattr(config, "default_managed_host", lambda: None)
        monkeypatch.setattr(config, "get_managed_host", lambda value: None)
        monkeypatch.setattr(network, "_resolve_mac_from_arp", lambda ip: None)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext(args=["192.168.1.10"])

        await network.cmd_wol(update, context)

        assert "Could not resolve MAC" in update.message.replies[-1]

    @pytest.mark.asyncio
    async def test_cmd_wolshutdown_runs_ssh_and_schedules_watch(
        self, monkeypatch
    ) -> None:
        async def mock_guard(update, context):
            return True

        scheduled: list[tuple[str, bool]] = []

        def fake_schedule(context, *, chat_id: int, host: str, online: bool) -> None:
            scheduled.append((host, online))

        monkeypatch.setattr(network, "guard_sensitive", mock_guard)
        monkeypatch.setattr(
            config,
            "default_managed_host",
            lambda: ManagedHost(
                name="gaming-pc",
                ping_host="192.168.1.10",
                ssh_target="pc-user@192.168.1.10",
                ssh_port=22,
                shutdown_command="sudo poweroff",
            ),
        )
        monkeypatch.setattr(config, "get_managed_host", lambda value: None)
        monkeypatch.setattr(network, "_schedule_power_state_watch", fake_schedule)

        with patch(
            "tele_home_supervisor.handlers.network.cli.run_cmd",
            new_callable=AsyncMock,
        ) as mock_run:
            mock_run.return_value = (0, "", "")
            update = DummyUpdate(chat_id=123, user_id=123)
            context = DummyContext(args=[])

            await network.cmd_wolshutdown(update, context)

        assert mock_run.await_count == 1
        assert scheduled == [("192.168.1.10", False)]
        assert "Sent shutdown command" in update.message.replies[-1]

    @pytest.mark.asyncio
    async def test_cmd_wol_selects_named_managed_host(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        packets: list[tuple[str, list[str], int]] = []

        monkeypatch.setattr(network, "guard_sensitive", mock_guard)
        monkeypatch.setattr(config, "default_managed_host", lambda: None)
        monkeypatch.setattr(
            config,
            "get_managed_host",
            lambda value: (
                ManagedHost(
                    name="gaming-pc",
                    ping_host="192.168.1.10",
                    mac="aa:bb:cc:dd:ee:ff",
                    wol_broadcast_ip="192.168.1.255",
                    wol_port=7,
                    aliases=("pc",),
                )
                if value == "pc"
                else None
            ),
        )
        monkeypatch.setattr(
            network,
            "_schedule_power_state_watch",
            lambda context, *, chat_id, host, online: None,
        )
        monkeypatch.setattr(
            network,
            "_send_wol_packet",
            lambda mac, *, broadcast_ips, port: packets.append(
                (mac, broadcast_ips, port)
            ),
        )

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext(args=["pc"])

        await network.cmd_wol(update, context)

        assert packets == [
            ("aa:bb:cc:dd:ee:ff", ["192.168.1.255", "255.255.255.255"], 7)
        ]

    @pytest.mark.asyncio
    async def test_cmd_traceroute_requires_args(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(network, "guard_sensitive", mock_guard)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext(args=[])

        await network.cmd_traceroute(update, context)

        assert "Usage" in update.message.replies[0]
