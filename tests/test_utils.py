import pytest
from unittest.mock import AsyncMock, patch
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
    with (
        patch(
            "tele_home_supervisor.cli.get_docker_cmd", return_value="/usr/bin/docker"
        ),
        patch("tele_home_supervisor.cli.run_cmd", new_callable=AsyncMock) as mock_run,
    ):
        output = "my-container\t5.0%\t10.0%\t50MiB\t1KB/2KB\t0B/0B\t123"
        mock_run.return_value = (0, output, "")

        stats = await utils.container_stats_rich()
        assert len(stats) == 1
        assert stats[0]["name"] == "my-container"
        assert stats[0]["cpu"] == "5.0%"
        assert stats[0]["pids"] == "123"


@pytest.mark.asyncio
async def test_speedtest_parser_success():
    with (
        patch("shutil.which", return_value="/usr/bin/curl"),
        patch("tele_home_supervisor.cli.run_cmd", new_callable=AsyncMock) as mock_run,
    ):
        # curl -w "%{{time_total}} %{{size_download}}" output
        # 2.0 seconds, 10,000,000 bytes (10MB)
        mock_run.return_value = (0, "2.0 10000000", "")

        result = await utils.speedtest_download(10)
        assert "Size: 10.0MB" in result
        assert "Time: 2.00s" in result
        # 10MB / 2s = 5MB/s. 5MB/s * 8 = 40Mbps
        assert "40.0 Mbps" in result


@pytest.mark.asyncio
async def test_speedtest_curl_missing():
    with patch("shutil.which", return_value=None):
        result = await utils.speedtest_download()
        assert "curl not available" in result
