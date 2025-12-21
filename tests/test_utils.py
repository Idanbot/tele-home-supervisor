import pytest
from unittest.mock import AsyncMock, Mock, patch
from tele_home_supervisor import utils


@pytest.mark.asyncio
async def test_get_primary_ip_success():
    with patch("tele_home_supervisor.cli.run_cmd", new_callable=AsyncMock) as mock_run:
        # Mock successful ip route command
        mock_run.return_value = (0, "192.168.1.50", "")

        ip = await utils.get_primary_ip()
        assert ip == "192.168.1.50"


@pytest.mark.asyncio
async def test_get_wan_ip_failure():
    with patch("tele_home_supervisor.cli.run_cmd", new_callable=AsyncMock) as mock_run:
        # Mock curl failure
        mock_run.return_value = (1, "", "timeout")

        ip = await utils.get_wan_ip()
        assert ip == "n/a"


@pytest.mark.asyncio
async def test_container_stats_rich_parsing():
    stats_payload = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 1250, "percpu_usage": [1, 1]},
            "system_cpu_usage": 100000,
            "online_cpus": 2,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 1000, "percpu_usage": [1, 1]},
            "system_cpu_usage": 90000,
        },
        "memory_stats": {"usage": 50 * 1024 * 1024, "limit": 500 * 1024 * 1024},
        "networks": {"eth0": {"rx_bytes": 1024, "tx_bytes": 2048}},
        "blkio_stats": {
            "io_service_bytes_recursive": [
                {"op": "Read", "value": 4096},
                {"op": "Write", "value": 8192},
            ]
        },
        "pids_stats": {"current": 123},
    }

    fake_container = Mock()
    fake_container.name = "my-container"
    fake_container.stats.return_value = stats_payload

    fake_client = Mock()
    fake_client.containers.list.return_value = [fake_container]

    with patch("tele_home_supervisor.utils.client", fake_client):
        stats = await utils.container_stats_rich()
    assert len(stats) == 1
    assert stats[0]["name"] == "my-container"
    assert stats[0]["cpu"] == "5.00%"
    assert stats[0]["pids"] == "123"


@pytest.mark.asyncio
async def test_speedtest_parser_success():
    with (
        patch("shutil.which", return_value="/usr/bin/curl"),
        patch("tele_home_supervisor.cli.run_cmd", new_callable=AsyncMock) as mock_run,
    ):
        # curl -w "TIME:%{time_total} SIZE:%{size_download}" output
        # 2.0 seconds, 10,000,000 bytes (10MB)
        mock_run.return_value = (0, "TIME:2.0 SIZE:10000000", "")

        result = await utils.speedtest_download(10)
        assert "Size: 10.0MB" in result
        assert "Time: 2.00s" in result
        # 10MB / 2s = 5MB/s. 5MB/s * 8 = 40Mbps = 40.00 Mb/s
        assert "40.00 Mb/s" in result


@pytest.mark.asyncio
async def test_speedtest_curl_missing():
    with patch("shutil.which", return_value=None):
        result = await utils.speedtest_download()
        assert "curl not available" in result
