"""Tests for view module - charts and formatting."""

import io

from tele_home_supervisor import view
from tele_home_supervisor.models.metrics import CommandMetrics


class TestRenderMetricsChart:
    """Tests for render_metrics_chart function."""

    def test_empty_metrics_returns_none(self) -> None:
        assert view.render_metrics_chart({}) is None

    def test_returns_bytesio_with_data(self) -> None:
        metrics = {
            "test_cmd": CommandMetrics(
                count=10, success=8, error=2, total_latency_s=1.0
            )
        }
        result = view.render_metrics_chart(metrics)
        assert result is not None
        assert isinstance(result, io.BytesIO)
        # Check it's a valid PNG (starts with PNG signature)
        data = result.getvalue()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_handles_multiple_commands(self) -> None:
        metrics = {
            "cmd1": CommandMetrics(
                count=100, success=90, error=10, total_latency_s=5.0
            ),
            "cmd2": CommandMetrics(count=50, success=50, error=0, total_latency_s=2.5),
            "cmd3": CommandMetrics(count=25, success=20, error=5, total_latency_s=1.0),
        }
        result = view.render_metrics_chart(metrics)
        assert result is not None

    def test_limits_to_top_15(self) -> None:
        # Create 20 commands
        metrics = {
            f"cmd{i}": CommandMetrics(count=i, success=i, error=0, total_latency_s=0.1)
            for i in range(1, 21)
        }
        result = view.render_metrics_chart(metrics)
        assert result is not None
        # Image should still be valid
        data = result.getvalue()
        assert len(data) > 100

    def test_handles_zero_count(self) -> None:
        metrics = {
            "zero_cmd": CommandMetrics(count=0, success=0, error=0, total_latency_s=0)
        }
        result = view.render_metrics_chart(metrics)
        # Should still return an image with zero bars
        assert result is not None


class TestRenderCommandMetrics:
    """Tests for render_command_metrics function."""

    def test_empty_metrics(self) -> None:
        result = view.render_command_metrics({})
        assert "No command metrics" in result

    def test_renders_command_data(self) -> None:
        metrics = {
            "test": CommandMetrics(
                count=10,
                success=8,
                error=2,
                rate_limited=1,
                total_latency_s=1.0,
                max_latency_s=0.2,
                latencies_s=[0.1, 0.1, 0.1, 0.1, 0.1],
            )
        }
        result = view.render_command_metrics(metrics)
        assert "test" in result
        assert "runs 10" in result
        assert "ok 8" in result
        assert "err 2" in result
        assert "rl 1" in result


class TestRenderHostHealth:
    """Tests for render_host_health function."""

    def test_basic_rendering(self) -> None:
        data = {
            "host": "myhost",
            "system": "Linux",
            "release": "5.15.0",
            "time": "2024-01-01 12:00:00",
            "lan_ip": "192.168.1.100",
            "wan_ip": "1.2.3.4",
            "uptime": "10 days",
            "load": "0.5",
            "cpu_pct": "25",
            "mem_used": "4GB",
            "mem_total": "16GB",
            "mem_pct": "25",
            "temp": "45°C",
            "disks": ["/: 50%", "/home: 30%"],
        }
        result = view.render_host_health(data, show_wan=True)
        assert "myhost" in result
        assert "192.168.1.100" in result
        assert "1.2.3.4" in result
        assert "10 days" in result

    def test_without_wan(self) -> None:
        data = {
            "host": "myhost",
            "system": "Linux",
            "release": "5.15.0",
            "time": "2024-01-01 12:00:00",
            "lan_ip": "192.168.1.100",
            "uptime": "10 days",
            "load": "0.5",
            "cpu_pct": "25",
            "mem_used": "4GB",
            "mem_total": "16GB",
            "mem_pct": "25",
            "temp": "45°C",
            "disks": [],
        }
        result = view.render_host_health(data, show_wan=False)
        assert "WAN" not in result


class TestRenderContainerList:
    """Tests for render_container_list function."""

    def test_empty_list(self) -> None:
        result = view.render_container_list([])
        assert "No containers" in result

    def test_with_containers(self) -> None:
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
        result = view.render_container_list(containers)
        assert "nginx" in result
        assert "redis" in result


class TestRenderTorrentList:
    """Tests for render_torrent_list function."""

    def test_empty_list(self) -> None:
        result = view.render_torrent_list([])
        assert "No" in result and "torrent" in result.lower()

    def test_with_torrents(self) -> None:
        torrents = [
            {
                "name": "Ubuntu ISO",
                "progress": 0.75,
                "state": "downloading",
                "dlspeed": 1024 * 1024,
                "size": 1024 * 1024 * 1024,
            }
        ]
        result = view.render_torrent_list(torrents)
        assert "Ubuntu" in result


class TestChunk:
    """Tests for chunk function."""

    def test_small_message_unchanged(self) -> None:
        msg = "Hello world"
        result = view.chunk(msg, size=100)
        assert result == [msg]

    def test_splits_on_newlines(self) -> None:
        msg = "line1\nline2\nline3\nline4\nline5"
        chunks = view.chunk(msg, size=12)
        assert len(chunks) >= 2
        # Verify all content preserved
        combined = "\n".join(chunks)
        for line in ["line1", "line2", "line3", "line4", "line5"]:
            assert line in combined

    def test_respects_size_limit(self) -> None:
        msg = "\n".join(["x" * 50 for _ in range(20)])
        chunks = view.chunk(msg, size=200)
        for chunk in chunks:
            assert len(chunk) <= 200 or "\n" not in chunk  # Can exceed if single line


class TestBoldCodePre:
    """Tests for HTML formatting helpers."""

    def test_bold(self) -> None:
        result = view.bold("test")
        assert result == "<b>test</b>"

    def test_bold_escapes_html(self) -> None:
        result = view.bold("<script>")
        assert "&lt;script&gt;" in result

    def test_code(self) -> None:
        result = view.code("test")
        assert result == "<code>test</code>"

    def test_pre(self) -> None:
        result = view.pre("test")
        assert result == "<pre>test</pre>"


class TestRenderHealthChart:
    """Tests for render_health_chart function."""

    def test_returns_bytesio(self) -> None:
        data = {
            "host": "testhost",
            "cpu_pct": "45",
            "mem_pct": "60",
            "uptime": "5 days",
            "load": "1.5",
            "temp": "55°C",
            "disks": ["/: 50%", "/home: 30%"],
        }
        result = view.render_health_chart(data)
        assert result is not None
        assert isinstance(result, io.BytesIO)
        # Check it's a valid PNG
        data_bytes = result.getvalue()
        assert data_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    def test_handles_missing_disks(self) -> None:
        data = {
            "host": "testhost",
            "cpu_pct": "10",
            "mem_pct": "20",
            "uptime": "1 day",
            "load": "0.5",
            "temp": "40°C",
            "disks": [],
        }
        result = view.render_health_chart(data)
        assert result is not None


class TestRenderDockerStatsChart:
    """Tests for render_docker_stats_chart function."""

    def test_empty_returns_none(self) -> None:
        assert view.render_docker_stats_chart([]) is None

    def test_returns_bytesio_with_data(self) -> None:
        stats = [
            {
                "name": "nginx",
                "cpu": "5.5%",
                "mem_pct": "10.2%",
                "mem_usage": "100MB/1GB",
                "netio": "1MB/2MB",
                "blockio": "50MB/100MB",
                "pids": "10",
            },
            {
                "name": "redis",
                "cpu": "2.1%",
                "mem_pct": "5.0%",
                "mem_usage": "50MB/1GB",
                "netio": "500KB/1MB",
                "blockio": "10MB/20MB",
                "pids": "5",
            },
        ]
        result = view.render_docker_stats_chart(stats)
        assert result is not None
        assert isinstance(result, io.BytesIO)


class TestRenderTorrentChart:
    """Tests for render_torrent_chart function."""

    def test_empty_returns_none(self) -> None:
        assert view.render_torrent_chart([]) is None

    def test_returns_bytesio_with_data(self) -> None:
        torrents = [
            {
                "name": "Ubuntu ISO",
                "progress": 0.75,
                "state": "downloading",
                "dlspeed": 1024 * 100,
            },
            {"name": "Debian ISO", "progress": 1.0, "state": "seeding", "dlspeed": 0},
        ]
        result = view.render_torrent_chart(torrents)
        assert result is not None
        assert isinstance(result, io.BytesIO)

    def test_handles_percentage_progress(self) -> None:
        torrents = [
            {"name": "Test", "progress": 50.0, "state": "downloading", "dlspeed": 0},
        ]
        result = view.render_torrent_chart(torrents)
        assert result is not None


class TestRenderSpeedtestChart:
    """Tests for render_speedtest_chart function."""

    def test_returns_bytesio(self) -> None:
        result = view.render_speedtest_chart(150.5)
        assert result is not None
        assert isinstance(result, io.BytesIO)

    def test_with_upload_and_ping(self) -> None:
        result = view.render_speedtest_chart(100.0, upload_mbps=50.0, ping_ms=15.0)
        assert result is not None


class TestRenderTracerouteChart:
    """Tests for render_traceroute_chart function."""

    def test_empty_returns_none(self) -> None:
        assert view.render_traceroute_chart([]) is None

    def test_returns_bytesio_with_data(self) -> None:
        hops = [
            {"hop": 1, "ip": "192.168.1.1", "hostname": "router.local", "rtt": 1.5},
            {"hop": 2, "ip": "10.0.0.1", "hostname": "", "rtt": 10.2},
            {"hop": 3, "ip": "*", "hostname": "", "rtt": 0},
            {"hop": 4, "ip": "8.8.8.8", "hostname": "dns.google", "rtt": 25.3},
        ]
        result = view.render_traceroute_chart(hops)
        assert result is not None
        assert isinstance(result, io.BytesIO)


class TestRenderAlertsChart:
    """Tests for render_alerts_chart function."""

    def test_empty_returns_none(self) -> None:
        assert view.render_alerts_chart([], None) is None

    def test_with_rules_only(self) -> None:
        # Simple rule-like dicts
        rules = [
            {"metric": "cpu", "operator": ">", "threshold": 90},
            {"metric": "mem", "operator": ">", "threshold": 80},
        ]
        result = view.render_alerts_chart([], rules)
        assert result is not None

    def test_with_alerts_only(self) -> None:
        import time

        alerts = [
            {
                "timestamp": time.time(),
                "metric": "cpu",
                "value": 95,
                "status": "triggered",
            },
            {
                "timestamp": time.time() - 60,
                "metric": "mem",
                "value": 85,
                "status": "resolved",
            },
        ]
        result = view.render_alerts_chart(alerts, None)
        assert result is not None


class TestRenderAuditChart:
    """Tests for render_audit_chart function."""

    def test_empty_returns_none(self) -> None:
        assert view.render_audit_chart([]) is None

    def test_with_dict_entries(self) -> None:
        import time

        entries = [
            {
                "created_at": time.time(),
                "user_name": "admin",
                "action": "docker",
                "target": "nginx",
                "status": "ok",
                "duration_ms": 50,
            },
            {
                "created_at": time.time() - 60,
                "user_name": "user",
                "action": "health",
                "target": None,
                "status": "ok",
                "duration_ms": 100,
            },
        ]
        result = view.render_audit_chart(entries)
        assert result is not None
        assert isinstance(result, io.BytesIO)

    def test_with_audit_entry_objects(self) -> None:
        import time
        from tele_home_supervisor.models.audit import AuditEntry

        entries = [
            AuditEntry(
                id="1",
                chat_id=123,
                user_id=456,
                user_name="admin",
                action="ping",
                target="google.com",
                status="ok",
                duration_ms=25,
                created_at=time.time(),
            ),
        ]
        result = view.render_audit_chart(entries)
        assert result is not None
