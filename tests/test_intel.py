from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from tele_home_supervisor import intel
from tele_home_supervisor.models.bot_state import BotState


@pytest.mark.asyncio
async def test_get_greeting():
    greeting = intel.get_greeting("TestUser")
    assert "Good" in greeting
    assert "TestUser" in greeting


@pytest.mark.asyncio
async def test_get_weather():
    with patch("tele_home_supervisor.intel._weather_request") as mock_request:
        mock_request.return_value = [
            {
                "current": {"temperature_2m": 25.5, "relative_humidity_2m": 50},
                "daily": {
                    "temperature_2m_max": [30.0],
                    "temperature_2m_min": [20.0],
                    "precipitation_sum": [0.0],
                },
            }
        ] * 3

        weather = await intel.get_weather()
        assert "Haifa" in weather
        assert "25.5°C" in weather
        assert "50%" in weather


@pytest.mark.asyncio
async def test_get_weather_falls_back_per_location():
    """Batch failure triggers per-location fallback; all locations succeed."""
    payload = {
        "current": {"temperature_2m": 21.0, "relative_humidity_2m": 60},
        "daily": {
            "temperature_2m_max": [24.0],
            "temperature_2m_min": [18.0],
            "precipitation_sum": [0.2],
        },
    }

    async def fake_weather_request(locations):
        if len(locations) > 1:
            raise httpx.ReadTimeout("batch timed out")
        return [payload]

    with patch(
        "tele_home_supervisor.intel._weather_request", side_effect=fake_weather_request
    ):
        weather = await intel.get_weather()

    assert "Haifa" in weather
    assert "Tel Aviv" in weather
    assert "21.0°C" in weather


@pytest.mark.asyncio
async def test_get_weather_per_location_retries_on_transient_failure():
    """A transient failure on Haifa is retried and the location shows data, not unavailable."""
    good_payload = {
        "current": {"temperature_2m": 18.6, "relative_humidity_2m": 87},
        "daily": {
            "temperature_2m_max": [22.7],
            "temperature_2m_min": [16.9],
            "precipitation_sum": [0.0],
        },
    }

    call_count = {"n": 0}

    async def fake_weather_request(locations):
        if len(locations) > 1:
            # batch always fails → triggers per-location fallback
            raise httpx.ReadTimeout("batch timed out")
        call_count["n"] += 1
        # Haifa is first; fail on the very first per-location call, succeed after
        if call_count["n"] == 1:
            raise httpx.ReadTimeout("transient timeout for Haifa")
        return [good_payload]

    with patch(
        "tele_home_supervisor.intel._weather_request", side_effect=fake_weather_request
    ):
        weather = await intel.get_weather()

    # Haifa must show temperature data, not "unavailable"
    assert "Haifa" in weather
    assert "unavailable" not in weather
    assert "18.6°C" in weather


@pytest.mark.asyncio
async def test_get_weather_per_location_all_retries_exhausted_shows_unavailable():
    """When all retries are exhausted for a location it shows 'unavailable'."""
    good_payload = {
        "current": {"temperature_2m": 21.0, "relative_humidity_2m": 60},
        "daily": {
            "temperature_2m_max": [24.0],
            "temperature_2m_min": [18.0],
            "precipitation_sum": [0.2],
        },
    }

    async def fake_weather_request(locations):
        if len(locations) > 1:
            raise httpx.ReadTimeout("batch timed out")
        # Identify Haifa by its latitude in the URL (first in list)
        # The simplest approach: always fail for lat 32.794 (Haifa)
        lat = locations[0].get("lat")
        if abs(lat - 32.7940) < 0.001:  # Haifa
            raise httpx.ReadTimeout("persistent timeout for Haifa")
        return [good_payload]

    with patch(
        "tele_home_supervisor.intel._weather_request", side_effect=fake_weather_request
    ):
        weather = await intel.get_weather()

    assert "Haifa" in weather
    assert "• <b>Haifa</b>: unavailable" in weather
    assert "Omer" in weather
    assert "21.0°C" in weather


@pytest.mark.asyncio
async def test_get_news():
    with patch("tele_home_supervisor.scheduled.fetch_hackernews_top") as mock_fetch:
        mock_fetch.return_value = "📰 Hacker News - Top Stories\n1. Story 1"
        news = await intel.get_news()
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
    response = MagicMock()
    response.json.return_value = {
        "text": "Don't explain your philosophy. Embody it.",
        "author": "Epictetus",
    }
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.get = AsyncMock(return_value=response)

    with patch("tele_home_supervisor.intel._get_client", return_value=client):
        quote = await intel.get_stoic_quote()
        assert "Epictetus" in quote
        assert "Embody it" in quote
        client.get.assert_awaited_once_with(
            "https://www.stoic-quotes.com/api/quote",
            follow_redirects=True,
        )


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
        patch("tele_home_supervisor.intel.get_reddit_digest", return_value="REDDIT"),
    ):
        intel_msg = await intel.build_intel_briefing(chat_id, state)

        assert "GREETING" in intel_msg
        assert "SYSTEM" in intel_msg
        assert "QUOTE" in intel_msg
        assert "REDDIT" in intel_msg
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


def test_clean_text_for_tts():
    raw = "☀️ <b>Good morning!</b> | • Weather: 22°C *Rain* 🌧️"
    cleaned = intel.clean_text_for_tts(raw)
    assert "☀️" not in cleaned
    assert "<b>" not in cleaned
    assert "•" not in cleaned
    assert "Good morning!" in cleaned
    assert "Weather: 22°C Rain" in cleaned


@pytest.mark.asyncio
async def test_get_weather_for_tts():
    fake_payloads = [
        {
            "daily": {
                "temperature_2m_max": [30.0],
                "temperature_2m_min": [20.0],
                "precipitation_probability_max": [10],
            }
        },
        {
            "daily": {
                "temperature_2m_max": [28.0],
                "temperature_2m_min": [22.0],
                "precipitation_probability_max": [40],
            }
        },
    ]
    with patch(
        "tele_home_supervisor.intel._fetch_weather_payloads",
        return_value=(fake_payloads, []),
    ):
        weather_summary = await intel.get_weather_for_tts()
        assert "25 degrees Celsius" in weather_summary
        assert "40 percent chance of rain" in weather_summary


@pytest.mark.asyncio
async def test_build_tts_announcer_raw_text_truncation():
    state = BotState()
    chat_id = 999

    with (
        patch(
            "tele_home_supervisor.intel.get_global_news",
            return_value=["Global news headline"],
        ),
        patch(
            "tele_home_supervisor.intel.get_israel_news",
            return_value=[
                "Israel headline 1",
                "Israel headline 2",
                "Israel headline 3",
            ],
        ),
        patch(
            "tele_home_supervisor.intel.scheduled_fetchers.fetch_hackernews_top",
            return_value="Hacker News\n1. HN Story One\n2. HN Story Two",
        ),
        patch(
            "tele_home_supervisor.intel.get_reddit_digest",
            return_value="Reddit\n1. Reddit Post One\n2. Reddit Post Two",
        ),
        patch(
            "tele_home_supervisor.intel.get_stoic_quote",
            return_value="Stoic quote test",
        ),
        patch(
            "tele_home_supervisor.intel.get_weather_for_tts",
            return_value="Weather test summary",
        ),
    ):
        # 1. Normal build under limit
        text = await intel.build_tts_announcer_raw_text(chat_id, state, max_chars=2000)
        assert "Greeting:" in text
        assert "Weather:" in text
        assert "Israel and World News:" in text
        assert "Hacker News:" in text
        assert "Reddit Trends:" in text
        assert "Stoic Wisdom:" in text

        # 2. Strict limit forces removing Reddit section first
        text_no_reddit = await intel.build_tts_announcer_raw_text(
            chat_id, state, max_chars=180
        )
        assert "Reddit Trends:" not in text_no_reddit
        assert "Israel and World News:" in text_no_reddit

        # 3. Very strict limit forces removing Hacker News section second
        text_no_hn = await intel.build_tts_announcer_raw_text(
            chat_id, state, max_chars=100
        )
        assert "Reddit Trends:" not in text_no_hn
        assert "Hacker News:" not in text_no_hn


@pytest.mark.asyncio
async def test_bot_state_intel_fire_time_and_tts_toggle():
    state = BotState()
    chat_id = 777

    # Test defaults
    assert state.get_intel_fire_time(chat_id) == (8, 0)
    assert not state.is_tts_announcer_enabled(chat_id)

    # Test setting fire time
    with patch.object(state, "save"):
        state.set_intel_fire_time(chat_id, 9, 30)
        assert state.get_intel_fire_time(chat_id) == (9, 30)

        # Test toggling TTS announcer
        enabled = state.toggle_tts_announcer(chat_id)
        assert enabled is True
        assert state.is_tts_announcer_enabled(chat_id) is True

        disabled = state.toggle_tts_announcer(chat_id)
        assert disabled is False
        assert state.is_tts_announcer_enabled(chat_id) is False


@pytest.mark.asyncio
async def test_tts_section_toggle_and_builder_filtering():
    state = BotState()
    chat_id = 888

    # Default: all sections enabled
    assert state.is_tts_section_enabled(chat_id, "weather")

    # Disable weather and greeting
    with patch.object(state, "save"):
        state.toggle_tts_section(chat_id, "weather")
        state.toggle_tts_section(chat_id, "greeting")

    assert not state.is_tts_section_enabled(chat_id, "weather")
    assert not state.is_tts_section_enabled(chat_id, "greeting")
    assert state.is_tts_section_enabled(chat_id, "news")

    with (
        patch(
            "tele_home_supervisor.intel.get_global_news",
            return_value=["Global news headline"],
        ),
        patch(
            "tele_home_supervisor.intel.get_israel_news",
            return_value=["Israel headline 1"],
        ),
        patch(
            "tele_home_supervisor.intel.get_stoic_quote",
            return_value="Stoic quote test",
        ),
        patch(
            "tele_home_supervisor.intel.get_weather_for_tts",
            return_value="Weather summary test",
        ),
    ):
        text = await intel.build_tts_announcer_raw_text(chat_id, state)
        assert "Greeting:" not in text
        assert "Weather:" not in text
        assert "Israel and World News:" in text
