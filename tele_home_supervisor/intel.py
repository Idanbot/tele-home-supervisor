from __future__ import annotations

import asyncio
import html
import logging
import re
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from defusedxml import ElementTree as ET

from . import config, utils
from . import scheduled as scheduled_fetchers
from .models.bot_state import BotState
from .orange_echo import OrangeEchoClient, OrangeEchoError
from .reddit_briefing import get_reddit_digest, get_reddit_digest_posts

logger = logging.getLogger(__name__)


_ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

INTEL_MODULES = [
    ("greeting", "👋 Greeting"),
    ("weather", "🌡️ Weather"),
    ("news", "📰 Hacker News"),
    ("system", "🖥️ System Health"),
    ("quote", "🏛️ Stoic Quote"),
    ("reddit", "👽 Reddit Radar"),
]

TTS_SECTIONS = [
    ("greeting", "👋 Greeting"),
    ("weather", "🌡️ Weather"),
    ("news", "📰 Israel & World News"),
    ("hackernews", "⚙️ Hacker News"),
    ("reddit", "👽 Reddit Trends"),
    ("quote", "🏛️ Stoic Quote"),
]


_WEATHER_TIMEOUT = httpx.Timeout(12.0, connect=3.5)
_WEATHER_RETRIES = 3  # per-location attempts in the fallback path

_CLIENT: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.AsyncClient(
            timeout=_WEATHER_TIMEOUT,
            transport=httpx.AsyncHTTPTransport(retries=2),
        )
    return _CLIENT


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


async def get_weather() -> str:
    """Weather module using Open-Meteo with resilient fallback fetches."""
    locations = [
        {"name": "Haifa", "lat": 32.7940, "lon": 34.9896},
        {"name": "Omer", "lat": 31.2464, "lon": 34.7961},
        {"name": "Tel Aviv", "lat": 32.0853, "lon": 34.7818},
    ]
    lines = ["🌡️ <b>Weather in Israel</b>"]
    data, failures = await _fetch_weather_payloads(locations)

    if not data:
        failure = failures[0] if failures else RuntimeError("unknown weather failure")
        logger.warning("Weather unavailable after retries: %s", failure)
        lines.append(
            f"❌ Weather unavailable right now: {html.escape(_format_fetch_error(failure))}"
        )
        return "\n".join(lines)

    try:
        for loc, payload in zip(locations, data, strict=False):
            if payload is None:
                lines.append(f"• <b>{loc['name']}</b>: unavailable")
                continue

            current = payload.get("current", {})
            daily = payload.get("daily", {})

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


async def get_news() -> str:
    """News Module - Top 5 Hacker News."""
    try:
        result = await scheduled_fetchers.fetch_hackernews_top(limit=5)
        if "Hacker News - Top Stories" in result:
            result = result.split("\n", 1)[1].strip()
        return f"📰 <b>Top Stories</b>\n{result}"
    except Exception as e:
        logger.exception("Failed to fetch news")
        return f"📰 <b>Top Stories</b>\n❌ News unavailable: {html.escape(str(e))}"


async def get_stoic_quote() -> str:
    """Quote Module - 1 Stoic Quote with retry."""
    quote, error = await fetch_stoic_quote()
    if quote is None:
        return f"🏛️ <b>Stoic Wisdom</b>\n❌ Wisdom unavailable today: {html.escape(error or 'unknown error')}"
    return f'🏛️ <b>Stoic Wisdom</b>\n<i>"{html.escape(quote.text)}"</i> — {html.escape(quote.author)}'


@dataclass(frozen=True)
class StoicQuote:
    text: str
    author: str


@dataclass(frozen=True)
class TTSBriefing:
    """Structured morning briefing data, independent of Telegram formatting."""

    recipient_name: str = "Idan"
    include_greeting: bool = True
    weather: str = ""
    global_news: tuple[str, ...] = ()
    israel_news: tuple[str, ...] = ()
    technology_news: tuple[str, ...] = ()
    reddit_news: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, object]:
        return {
            "recipient_name": self.recipient_name,
            "include_greeting": self.include_greeting,
            "weather": self.weather,
            "global_news": list(self.global_news),
            "israel_news": list(self.israel_news),
            "technology_news": list(self.technology_news),
            "reddit_news": list(self.reddit_news),
        }


async def fetch_stoic_quote() -> tuple[StoicQuote | None, str | None]:
    """Fetch structured quote data so narration can preserve it verbatim."""
    url = "https://www.stoic-quotes.com/api/quote"
    data = None
    last_error = None
    client = _get_client()

    for attempt in range(2):
        try:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            data = response.json()
            break
        except Exception as e:
            last_error = e
            logger.warning("Stoic quote fetch attempt %d failed: %s", attempt + 1, e)

    if not data:
        return None, str(last_error)

    quote = str(data.get("text") or "").strip()
    author = str(data.get("author") or "Unknown").strip()
    if not quote:
        return None, "No quote found"
    return StoicQuote(text=quote, author=author), None


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

    tasks = []

    if "greeting" not in disabled:
        tasks.append(asyncio.to_thread(get_greeting, "Idan"))

    if "weather" not in disabled:
        tasks.append(get_weather())

    if "news" not in disabled:
        tasks.append(get_news())

    if "system" not in disabled:
        tasks.append(get_system_health())

    if "quote" not in disabled:
        tasks.append(get_stoic_quote())

    if "reddit" not in disabled and state is not None and chat_id is not None:
        tasks.append(get_reddit_digest(state.get_reddit_settings(chat_id)))

    if not tasks:
        return (
            "☀️ <b>Good morning!</b>\n\nAll intel modules are disabled. "
            "Use /intel_settings to enable some."
        )

    results = await asyncio.gather(*tasks)

    return "\n\n".join(results)


async def _fetch_weather_payloads(
    locations: list[dict[str, float | str]],
) -> tuple[list[dict[str, Any] | None], list[Exception]]:
    """Fetch weather for all locations, falling back to per-location requests."""
    failures: list[Exception] = []

    try:
        batch_data = await _weather_request(locations)
        if len(batch_data) == len(locations):
            return batch_data, failures
        logger.warning(
            "Weather batch response size mismatch: expected %d locations, got %d",
            len(locations),
            len(batch_data),
        )
    except Exception as exc:
        logger.warning("Batch weather fetch failed, retrying per location: %s", exc)
        failures.append(exc)

    payloads: list[dict[str, Any] | None] = []
    for loc in locations:
        payload: dict[str, Any] | None = None
        last_exc: Exception | None = None
        for attempt in range(_WEATHER_RETRIES):
            try:
                res = await _weather_request([loc])
                payload = res[0]
                break
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Weather fetch failed for %s (attempt %d/%d): %s",
                    loc["name"],
                    attempt + 1,
                    _WEATHER_RETRIES,
                    exc,
                )
        if payload is None and last_exc is not None:
            failures.append(last_exc)
        payloads.append(payload)
    return payloads, failures


async def _weather_request(
    locations: list[dict[str, float | str]],
) -> list[dict[str, Any]]:
    url = _build_weather_url(locations)
    client = _get_client()
    response = await client.get(url)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list):
        return data
    return [data]


def _build_weather_url(locations: list[dict[str, float | str]]) -> str:
    lats = ",".join(str(loc["lat"]) for loc in locations)
    lons = ",".join(str(loc["lon"]) for loc in locations)
    return (
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={lats}&longitude={lons}&"
        "current=temperature_2m,relative_humidity_2m,weather_code&"
        "daily=temperature_2m_max,temperature_2m_min,precipitation_sum,"
        "precipitation_probability_max&"
        "forecast_days=1&timezone=auto"
    )


def _format_fetch_error(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return exc.__class__.__name__
    if len(message) > 120:
        return f"{message[:117]}..."
    return message


_ISRAEL_NEWS_FEEDS = [
    "https://www.timesofisrael.com/feed/",
    "https://www.jpost.com/rss/rssfeedsfrontpage.aspx",
    "https://www.ynetnews.com/Integration/StoryRss1854.xml",
]

_GLOBAL_NEWS_FEEDS = [
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
]


async def fetch_rss_headlines(urls: list[str], limit: int) -> list[str]:
    """Fetch headlines from a list of RSS feed URLs."""
    client = _get_client()
    titles: list[str] = []
    for url in urls:
        try:
            res = await client.get(url, follow_redirects=True)
            res.raise_for_status()
            root = ET.fromstring(res.content)
            for item in root.findall(".//item"):
                t = item.find("title")
                if t is not None and t.text:
                    cleaned = html.unescape(t.text).strip()
                    cleaned = re.sub(r"<[^>]+>", "", cleaned).strip()
                    if cleaned and cleaned not in titles:
                        titles.append(cleaned)
                        if len(titles) >= limit:
                            return titles
        except Exception as exc:
            logger.warning("Failed to fetch RSS from %s: %s", url, exc)
            continue
    return titles


async def get_israel_news(limit: int = 3) -> list[str]:
    """Fetch top Israel news headlines from RSS sources."""
    return await fetch_rss_headlines(_ISRAEL_NEWS_FEEDS, limit)


async def get_global_news(limit: int = 1) -> list[str]:
    """Fetch top global news headline from RSS sources."""
    return await fetch_rss_headlines(_GLOBAL_NEWS_FEEDS, limit)


def clean_text_for_tts(text: str) -> str:
    """Remove HTML, emojis, markdown formatting, and symbols that ruin TTS."""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(
        r"[\U00010000-\U0010ffff\u2600-\u27ff\u2300-\u23ff\u2b05\u2934\u2935\u25b6\u25c0]",
        "",
        text,
    )
    text = re.sub(r"[*_`#~|•]", "", text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


async def get_weather_for_tts() -> str:
    """Weather summary formatted for TTS with a daily average for each city."""
    locations = [
        {"name": "Haifa", "lat": 32.7940, "lon": 34.9896},
        {"name": "Omer", "lat": 31.2464, "lon": 34.7961},
        {"name": "Tel Aviv", "lat": 32.0853, "lon": 34.7818},
    ]
    data, _ = await _fetch_weather_payloads(locations)
    city_temperatures = []
    precip_probs = []
    for index, location in enumerate(locations):
        city_name = str(location["name"])
        payload = data[index] if index < len(data) else None
        if not payload:
            city_temperatures.append(f"{city_name} is unavailable")
            continue
        daily = payload.get("daily", {})
        t_max = daily.get("temperature_2m_max", [None])[0]
        t_min = daily.get("temperature_2m_min", [None])[0]
        p_prob = daily.get("precipitation_probability_max", [None])[0]
        if t_max is not None and t_min is not None:
            average = round((t_max + t_min) / 2.0)
            city_temperatures.append(f"{city_name} averages {average} degrees Celsius")
        else:
            city_temperatures.append(f"{city_name} is unavailable")
        if p_prob is not None:
            precip_probs.append(p_prob)

    rain_chance = max(precip_probs) if precip_probs else 0

    return (
        f"Today's average temperatures: {'; '.join(city_temperatures)}. "
        f"with a {rain_chance} percent chance of rain."
    )


async def build_tts_announcer_briefing(
    chat_id: int | None = None,
    state: BotState | None = None,
    max_chars: int = 1200,
) -> TTSBriefing:
    """Build structured source data for a natural morning narration."""
    disabled_tts = set()
    if chat_id is not None and state is not None:
        disabled_tts = state.get_disabled_tts_sections(chat_id)

    weather = ""
    if "weather" not in disabled_tts:
        weather = await get_weather_for_tts()

    global_news: list[str] = []
    israel_news: list[str] = []
    if "news" not in disabled_tts:
        global_news, israel_news = await asyncio.gather(
            get_global_news(1), get_israel_news(3)
        )

    technology_news: list[str] = []
    if "hackernews" not in disabled_tts:
        try:
            stories = await scheduled_fetchers.fetch_hackernews_stories(limit=3)
            technology_news = [
                clean_text_for_tts(str(story.get("title") or ""))
                for story in stories
                if story.get("title")
            ][:3]
        except Exception as exc:
            logger.warning("Failed to fetch Hacker News for TTS: %s", exc)

    reddit_news: list[str] = []
    if "reddit" not in disabled_tts and state is not None and chat_id is not None:
        try:
            posts = await get_reddit_digest_posts(state.get_reddit_settings(chat_id))
            reddit_news = [
                clean_text_for_tts(str(post.get("title") or ""))
                for post in posts
                if post.get("title")
            ][:3]
        except Exception as exc:
            logger.warning("Failed to fetch Reddit for TTS: %s", exc)

    briefing = TTSBriefing(
        include_greeting="greeting" not in disabled_tts,
        weather=weather,
        global_news=tuple(global_news),
        israel_news=tuple(israel_news),
        technology_news=tuple(technology_news),
        reddit_news=tuple(reddit_news),
    )
    if len(render_tts_briefing(briefing)) <= max_chars:
        return briefing
    briefing = dataclass_replace(briefing, reddit_news=())
    if len(render_tts_briefing(briefing)) <= max_chars:
        return briefing
    return dataclass_replace(briefing, technology_news=())


async def build_tts_announcer_raw_text(
    chat_id: int | None = None,
    state: BotState | None = None,
    max_chars: int = 1200,
    include_quote: bool = True,
) -> str:
    """Build legacy text for callers that have not moved to structured briefings."""
    briefing = await build_tts_announcer_briefing(chat_id, state, max_chars)
    narration = render_tts_briefing(briefing)
    quote_enabled = (
        state is None
        or chat_id is None
        or state.is_tts_section_enabled(chat_id, "quote")
    )
    if include_quote and quote_enabled:
        quote, _ = await fetch_stoic_quote()
        narration = _fallback_tts_narration(briefing, quote, max_chars)
    return narration


def render_tts_briefing(briefing: TTSBriefing) -> str:
    """Render a structured briefing without speaking internal section labels."""
    parts: list[str] = []
    if briefing.include_greeting:
        parts.append(f"Good morning, {briefing.recipient_name}.")
    if briefing.weather:
        parts.append(f"Starting with the weather. {briefing.weather}")
    if briefing.global_news:
        parts.append(f"In world news. {' '.join(briefing.global_news)}")
    if briefing.israel_news:
        parts.append(f"Closer to home. {' '.join(briefing.israel_news)}")
    if briefing.technology_news:
        parts.append(f"Turning to technology. {' '.join(briefing.technology_news)}")
    if briefing.reddit_news:
        parts.append(f"A quick look at Reddit. {' '.join(briefing.reddit_news)}")
    return " ".join(parts)


def _fallback_tts_narration(
    source: str | TTSBriefing, quote: StoicQuote | None, limit: int = 1400
) -> str:
    closing = ""
    if quote:
        closing = f' To close, today\'s Stoic thought. "{quote.text}" - {quote.author}.'
    body = render_tts_briefing(source) if isinstance(source, TTSBriefing) else source
    body_budget = max(0, limit - len(closing))
    if len(body) > body_budget:
        body = body[:body_budget].rsplit(" ", 1)[0].rstrip(".,;: ")
    return f"{body}{closing}".strip()


def _optimizer_narration_is_complete(narration: str, quote: StoicQuote | None) -> bool:
    normalized = narration.strip()
    if not normalized:
        return False
    if quote and (quote.text not in normalized or quote.author not in normalized):
        return False

    return True


async def generate_tts_announcer_audio(
    raw_text: str | TTSBriefing,
    state: BotState | None = None,
    chat_id: int | None = None,
) -> tuple[bytes | None, str | None]:
    """Send raw TTS text to Cloudflare Workers AI (Orange Echo) optimize & speech pipeline."""
    if not config.ORANGE_ECHO_API_KEY:
        err_msg = "ORANGE_ECHO_API_KEY environment variable is not configured."
        logger.warning(err_msg)
        return None, err_msg

    from .orange_echo import track_cf_action

    client = OrangeEchoClient(
        base_url=config.ORANGE_ECHO_BASE_URL,
        api_key=config.ORANGE_ECHO_API_KEY,
    )
    try:

        async def _run_pipeline() -> bytes:
            quote: StoicQuote | None = None
            quote_payload = None
            quote_enabled = (
                chat_id is None
                or state is None
                or state.is_tts_section_enabled(chat_id, "quote")
            )
            if quote_enabled:
                quote, quote_error = await fetch_stoic_quote()
                if quote:
                    quote_payload = {"text": quote.text, "author": quote.author}
                elif quote_error:
                    logger.warning("Stoic quote omitted from TTS: %s", quote_error)
            legacy_text = (
                render_tts_briefing(raw_text)
                if isinstance(raw_text, TTSBriefing)
                else raw_text
            )
            if legacy_text.strip():
                if isinstance(raw_text, TTSBriefing):
                    narration = await client.optimize(
                        legacy_text,
                        target_characters=1400,
                        stoic_quote=quote_payload,
                        briefing=raw_text.as_payload(),
                    )
                else:
                    narration = await client.optimize(
                        legacy_text,
                        target_characters=1400,
                        stoic_quote=quote_payload,
                    )
            else:
                narration = ""
            if not _optimizer_narration_is_complete(narration, quote):
                logger.warning(
                    "Optimizer returned incomplete TTS narration; using structured fallback"
                )
                narration = _fallback_tts_narration(raw_text, quote)
            model = (
                state.get_cf_model(chat_id, "speech")
                if state and chat_id
                else "premium"
            )
            voice_preset = state.get_cf_voice(chat_id) if state and chat_id else "luna"
            return await client.synthesize(
                narration,
                model=model,
                voice_preset=voice_preset,
            )

        audio_bytes = await track_cf_action(
            client, state, "TTS Announcer (briefing)", _run_pipeline()
        )
        return audio_bytes, None
    except OrangeEchoError as e:
        logger.warning("Cloudflare Workers AI TTS announcer failed: %s", e)
        return None, e.user_friendly_message()
    except Exception as e:
        logger.exception("Failed to generate TTS announcer audio: %s", e)
        return None, f"❌ Cloudflare Workers AI error: {html.escape(str(e))}"
    finally:
        await client.close()
