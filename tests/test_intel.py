import pytest
from unittest.mock import patch, MagicMock
from tele_home_supervisor import intel
from tele_home_supervisor.models.bot_state import BotState


@pytest.mark.asyncio
async def test_get_greeting():
    greeting = intel.get_greeting("TestUser")
    assert "Good" in greeting
    assert "TestUser" in greeting


@pytest.mark.asyncio
async def test_get_weather():
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = {
            "current": {"temperature_2m": 25.5, "relative_humidity_2m": 50},
            "daily": {
                "temperature_2m_max": [30.0],
                "temperature_2m_min": [20.0],
                "precipitation_sum": [0.0],
            },
        }
        mock_get.return_value.raise_for_status = MagicMock()

        weather = intel.get_weather()
        assert "Haifa" in weather
        assert "25.5°C" in weather
        assert "50%" in weather


@pytest.mark.asyncio
async def test_get_news():
    with patch("tele_home_supervisor.scheduled.fetch_hackernews_top") as mock_fetch:
        mock_fetch.return_value = "📰 Hacker News - Top Stories\n1. Story 1"
        news = intel.get_news()
        assert "Story 1" in news
        assert "Hacker News - Top Stories" not in news


@pytest.mark.asyncio
async def test_get_system_health():
    with patch("tele_home_supervisor.utils.host_health") as mock_health:
        mock_health.return_value = {
            "cpu_pct": 10,
            "temp": "45.0°C",
            "mem_used": "1GB",
            "mem_total": "8GB",
            "mem_pct": 12,
            "uptime": "1 day",
            "load": "0.1 0.2 0.3",
            "disks": ["/: 10GB/100GB (10%)"],
        }
        health = await intel.get_system_health()
        assert "<b>CPU:</b> 10%" in health
        assert "<b>Temp:</b> 45.0°C" in health
        assert "<b>Uptime:</b> 1 day" in health


@pytest.mark.asyncio
async def test_get_stoic_quote():
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = {
            "text": "Don't explain your philosophy. Embody it.",
            "author": "Epictetus",
        }
        mock_get.return_value.raise_for_status = MagicMock()

        quote = intel.get_stoic_quote()
        assert "Epictetus" in quote
        assert "Embody it" in quote


@pytest.mark.asyncio
async def test_build_intel_briefing_filtering():
    state = BotState()
    chat_id = 12345

    # Disable weather and news
    state.disabled_intel_modules[chat_id] = {"weather", "news"}

    with (
        patch("tele_home_supervisor.intel.get_greeting", return_value="GREETING"),
        patch("tele_home_supervisor.intel.get_weather", return_value="WEATHER"),
        patch("tele_home_supervisor.intel.get_news", return_value="NEWS"),
        patch("tele_home_supervisor.intel.get_system_health", return_value="SYSTEM"),
        patch("tele_home_supervisor.intel.get_stoic_quote", return_value="QUOTE"),
    ):
        intel_msg = await intel.build_intel_briefing(chat_id, state)

        assert "GREETING" in intel_msg
        assert "SYSTEM" in intel_msg
        assert "QUOTE" in intel_msg
        assert "WEATHER" not in intel_msg
        assert "NEWS" not in intel_msg


@pytest.mark.asyncio
async def test_build_intel_briefing_all_disabled():
    state = BotState()
    chat_id = 12345

    # Disable all modules
    state.disabled_intel_modules[chat_id] = {m[0] for m in intel.INTEL_MODULES}

    intel_msg = await intel.build_intel_briefing(chat_id, state)
    assert "All intel modules are disabled" in intel_msg
