from __future__ import annotations

import html
import logging
import asyncio
import time
from datetime import datetime

import requests
from zoneinfo import ZoneInfo

from . import scheduled as scheduled_fetchers
from . import utils
from .models.bot_state import BotState

logger = logging.getLogger(__name__)

_ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

INTEL_MODULES = [
    ("greeting", "👋 Greeting"),
    ("weather", "🌡️ Weather"),
    ("news", "📰 Hacker News"),
    ("system", "🖥️ System Health"),
    ("quote", "🏛️ Stoic Quote"),
]


def get_greeting(name: str = "Idan") -> str:
    """Greeting Module."""
    now = datetime.now(_ISRAEL_TZ)
    hour = now.hour

    if 5 <= hour < 12:
        period = "morning"
    elif 12 <= hour < 18:
        period = "afternoon"
    elif 18 <= hour < 22:
        period = "evening"
    else:
        period = "night"

    return f"☀️ <b>Good {period}, {name}!</b>"


def get_weather() -> str:
    """Weather Module using Open-Meteo with retry."""
    locations = [
        {"name": "Haifa", "lat": 32.7940, "lon": 34.9896},
        {"name": "Omer", "lat": 31.2464, "lon": 34.7961},
        {"name": "Tel Aviv", "lat": 32.0853, "lon": 34.7818},
    ]

    lines = ["🌡️ <b>Weather in Israel</b>"]

    # Multi-location request
    lats = ",".join(str(loc["lat"]) for loc in locations)
    lons = ",".join(str(loc["lon"]) for loc in locations)

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lats}&longitude={lons}&"
        f"current=temperature_2m,relative_humidity_2m,weather_code&"
        f"daily=temperature_2m_max,temperature_2m_min,precipitation_sum&"
        f"timezone=auto"
    )

    data = None
    last_error = None

    for attempt in range(2):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            break
        except Exception as e:
            last_error = e
            logger.warning("Weather fetch attempt %d failed: %s", attempt + 1, e)
            if attempt == 0:
                time.sleep(5)

    if not data:
        logger.exception("Failed to fetch weather after retries")
        lines.append(f"❌ Weather unavailable: {html.escape(str(last_error))}")
        return "\n".join(lines)

    try:
        # Open-Meteo returns a list if multiple locations are requested
        if not isinstance(data, list):
            data = [data]

        for i, loc in enumerate(locations):
            current = data[i].get("current", {})
            daily = data[i].get("daily", {})

            temp = current.get("temperature_2m", "?")
            humidity = current.get("relative_humidity_2m", "?")
            temp_max = daily.get("temperature_2m_max", [None])[0]
            temp_min = daily.get("temperature_2m_min", [None])[0]
            precip = daily.get("precipitation_sum", [None])[0]

            line = f"• <b>{loc['name']}</b>: {temp}°C (L:{temp_min} H:{temp_max}) | 💧 {humidity}% | 🌧️ {precip}mm"
            lines.append(line)

    except Exception as e:
        logger.exception("Failed to process weather data")
        lines.append(f"❌ Weather processing error: {html.escape(str(e))}")

    return "\n".join(lines)


def get_news() -> str:
    """News Module - Top 5 Hacker News."""
    try:
        # Reuse existing fetcher with limit 5
        result = scheduled_fetchers.fetch_hackernews_top(limit=5)
        # Remove the header if it exists to fit in the intel format
        if "Hacker News - Top Stories" in result:
            result = result.split("\n", 1)[1].strip()
        return f"📰 <b>Top Stories</b>\n{result}"
    except Exception as e:
        logger.exception("Failed to fetch news")
        return f"📰 <b>Top Stories</b>\n❌ News unavailable: {html.escape(str(e))}"


def get_stoic_quote() -> str:
    """Quote Module - 1 Stoic Quote with retry."""
    url = "https://stoic-quotes.com/api/quote"
    data = None
    last_error = None

    for attempt in range(2):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            break
        except Exception as e:
            last_error = e
            logger.warning("Stoic quote fetch attempt %d failed: %s", attempt + 1, e)
            if attempt == 0:
                time.sleep(5)

    if not data:
        logger.exception("Failed to fetch stoic quote after retries")
        return f"🏛️ <b>Stoic Wisdom</b>\n❌ Wisdom unavailable today: {html.escape(str(last_error))}"

    quote = data.get("text", "No quote found")
    author = data.get("author", "Unknown")

    return f'🏛️ <b>Stoic Wisdom</b>\n<i>"{quote}"</i> — {author}'


async def get_system_health() -> str:
    """System Health Module."""
    try:
        data = await utils.host_health()

        lines = [
            "🖥️ <b>System Health</b>",
            f"• <b>CPU:</b> {data['cpu_pct']}% | <b>Temp:</b> {data['temp']}",
            f"• <b>Mem:</b> {data['mem_used']} / {data['mem_total']} ({data['mem_pct']}%)",
            f"• <b>Uptime:</b> {data['uptime']}",
            f"• <b>Load:</b> {data['load']}",
        ]

        # Add primary disk usage (usually first one)
        if data.get("disks"):
            lines.append(f"• <b>Disk:</b> {data['disks'][0]}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("Failed to fetch system health")
        return f"🖥️ <b>System Health</b>\n❌ Stats unavailable: {html.escape(str(e))}"


async def build_intel_briefing(
    chat_id: int | None = None, state: BotState | None = None
) -> str:
    """Orchestrate all modules into a single message."""
    disabled = set()
    if chat_id is not None and state is not None:
        disabled = state.disabled_intel_modules.get(chat_id, set())

    loop = asyncio.get_running_loop()

    tasks = []

    # We define the order here
    if "greeting" not in disabled:
        tasks.append(asyncio.to_thread(get_greeting, "Idan"))

    if "weather" not in disabled:
        tasks.append(loop.run_in_executor(None, get_weather))

    if "news" not in disabled:
        tasks.append(loop.run_in_executor(None, get_news))

    if "system" not in disabled:
        tasks.append(get_system_health())

    if "quote" not in disabled:
        tasks.append(loop.run_in_executor(None, get_stoic_quote))

    if not tasks:
        return (
            "☀️ <b>Good morning!</b>\n\nAll intel modules are disabled. "
            "Use /intel_settings to enable some."
        )

    results = await asyncio.gather(*tasks)

    return "\n\n".join(results)
