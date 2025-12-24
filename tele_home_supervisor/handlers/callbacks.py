"""Callback query handlers for inline keyboard buttons."""

from __future__ import annotations

import asyncio
import html
import logging
import math
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest

from .. import services, tmdb, view, protondb
from ..state import BotState
from .common import allowed, get_state

logger = logging.getLogger(__name__)

DOCKER_PAGE_SIZE = 8
LOG_PAGE_SIZE = 50
LOG_PAGE_STEP = 45
LOG_LINE_MAX = 300


def normalize_docker_page(total_items: int, page: int) -> tuple[int, int]:
    total_pages = max(1, math.ceil(total_items / DOCKER_PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    return page, total_pages


async def _safe_edit_message_text(query, text: str, **kwargs) -> None:
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        if "Message is not modified" in str(exc):
            return
        raise


def _trim_log_line(line: str) -> str:
    if len(line) <= LOG_LINE_MAX:
        return line
    return f"{line[: LOG_LINE_MAX - 3]}..."


def _parse_log_page_payload(
    data: str, prefix: str
) -> tuple[str, int, int | None] | None:
    payload = data[len(prefix) :]
    parts = payload.split(":")
    if len(parts) < 2:
        return None
    if len(parts) == 2:
        container, start_raw = parts
        since_raw = None
    else:
        container = ":".join(parts[:-2])
        start_raw = parts[-2]
        since_raw = parts[-1]
    if not container:
        return None
    try:
        start = max(int(start_raw), 0)
    except ValueError:
        start = 0
    since = None
    if since_raw:
        try:
            since = int(since_raw)
        except ValueError:
            since = None
    return container, start, since


async def _get_log_lines(
    state: BotState, container: str, refresh: bool, since: int | None = None
) -> list[str]:
    if since is None and not refresh:
        cached = state.get_log_cache(container)
        if cached is not None:
            return cached
    raw = await services.get_container_logs_full(container, since=since)
    lines = raw.splitlines() if raw else []
    if since is None:
        state.set_log_cache(container, lines)
    return lines


def _render_logs_page(
    container: str, lines: list[str], start: int, since: int | None = None
) -> tuple[str, InlineKeyboardMarkup | None, int]:
    total = len(lines)
    if total == 0:
        return "<i>No logs found.</i>", None, 0
    max_start = max(0, total - LOG_PAGE_SIZE)
    start = max(0, min(start, max_start))
    end = min(start + LOG_PAGE_SIZE, total)
    header = (
        f"{view.bold(f'Logs for {html.escape(container)}')} "
        f"<i>(lines {start + 1}-{end} of {total})</i>\n"
    )
    display_lines = [_trim_log_line(line) for line in lines[start:end]]
    max_len = 3600
    if display_lines:
        allowed = max(
            20,
            (max_len - len(header) - 11) // max(1, len(display_lines)),
        )
        if allowed < LOG_LINE_MAX:
            display_lines = [_trim_log_line(line[:allowed]) for line in display_lines]
    msg = f"{header}{view.pre('\\n'.join(display_lines))}"

    buttons: list[list[InlineKeyboardButton]] = []
    nav_row: list[InlineKeyboardButton] = []
    if start > 0:
        prev_start = max(0, start - LOG_PAGE_STEP)
        nav_row.append(
            InlineKeyboardButton(
                "⬆️ Older",
                callback_data=_format_log_callback(
                    container, prev_start, since, "page"
                ),
            )
        )
    nav_row.append(
        InlineKeyboardButton(
            "⬇️ Tail",
            callback_data=_format_log_callback(container, max_start, since, "page"),
        )
    )
    if start < max_start:
        next_start = min(max_start, start + LOG_PAGE_STEP)
        nav_row.append(
            InlineKeyboardButton(
                "⬇️ Newer",
                callback_data=_format_log_callback(
                    container, next_start, since, "page"
                ),
            )
        )
    if nav_row:
        buttons.append(nav_row)
    buttons.append(
        [
            InlineKeyboardButton(
                "🔄 Refresh",
                callback_data=_format_log_callback(container, start, since, "refresh"),
            )
        ]
    )
    return msg, InlineKeyboardMarkup(buttons), start


def _format_log_callback(
    container: str, start: int, since: int | None, action: str
) -> str:
    if since is None:
        return f"dlogs:{action}:{container}:{start}"
    return f"dlogs:{action}:{container}:{start}:{since}"


def build_docker_keyboard(containers: list[str], page: int = 0) -> InlineKeyboardMarkup:
    """Build inline keyboard with container action buttons."""
    buttons: list[list[InlineKeyboardButton]] = []
    page, total_pages = normalize_docker_page(len(containers), page)
    start = page * DOCKER_PAGE_SIZE
    end = start + DOCKER_PAGE_SIZE
    for name in containers[start:end]:
        buttons.append(
            [
                InlineKeyboardButton(
                    f"📜 {name[:12]}", callback_data=f"dlogs:{name[:30]}"
                ),
                InlineKeyboardButton("❤️", callback_data=f"dhealth:{name[:30]}"),
                InlineKeyboardButton("📊", callback_data=f"dstats:{name[:30]}"),
            ]
        )
    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton("⬅️ Prev", callback_data=f"docker:page:{page - 1}")
            )
        nav_row.append(
            InlineKeyboardButton(
                f"📄 {page + 1}/{total_pages}", callback_data="docker:noop"
            )
        )
        if page + 1 < total_pages:
            nav_row.append(
                InlineKeyboardButton("Next ➡️", callback_data=f"docker:page:{page + 1}")
            )
        buttons.append(nav_row)
    buttons.append(
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"docker:refresh:{page}")]
    )
    return InlineKeyboardMarkup(buttons)


def build_torrent_keyboard(torrents: list[dict]) -> InlineKeyboardMarkup:
    """Build inline keyboard with torrent action buttons."""
    buttons = []
    for t in torrents[:6]:
        name = t.get("name", "Unknown")[:20]
        torrent_hash = t.get("hash", "")[:16]
        state = t.get("state", "")

        row = [
            InlineKeyboardButton(f"📁 {name}", callback_data=f"tinfo:{torrent_hash}")
        ]

        if state in ("downloading", "uploading", "stalledDL", "stalledUP", "queuedDL"):
            row.append(InlineKeyboardButton("⏸️", callback_data=f"tstop:{torrent_hash}"))
        else:
            row.append(
                InlineKeyboardButton("▶️", callback_data=f"tstart:{torrent_hash}")
            )

        buttons.append(row)

    buttons.append(
        [InlineKeyboardButton("🔄 Refresh", callback_data="torrent:refresh")]
    )
    return InlineKeyboardMarkup(buttons)


def build_tmdb_keyboard(
    key: str, items: list[dict[str, object]], page: int, total_pages: int
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, item in enumerate(items, start=1):
        title = str(item.get("title") or item.get("name") or "Unknown")
        media_type = str(item.get("media_type") or "")
        item_id = item.get("id")
        if not item_id or media_type not in {"movie", "tv"}:
            continue
        label = f"{idx}. {title}"
        if len(label) > 60:
            label = f"{label[:57]}..."
        buttons.append(
            [
                InlineKeyboardButton(
                    label, callback_data=f"tmdbinfo:{media_type}:{item_id}"
                )
            ]
        )
    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton("⬅️ Prev", callback_data=f"tmdbpage:{key}:{page - 1}")
        )
    nav_row.append(
        InlineKeyboardButton(
            f"📄 {page}/{max(total_pages, 1)}",
            callback_data=f"tmdbpage:{key}:{page}",
        )
    )
    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton("Next ➡️", callback_data=f"tmdbpage:{key}:{page + 1}")
        )
    if nav_row:
        buttons.append(nav_row)
    return InlineKeyboardMarkup(buttons)


def build_protondb_keyboard(key: str, games: list[dict]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, game in enumerate(games):
        name = str(game.get("name") or "Unknown")
        appid = str(game.get("appid") or "")
        if not appid:
            continue
        label = f"{idx + 1}. {name}"
        if len(label) > 60:
            label = f"{label[:57]}..."
        buttons.append(
            [InlineKeyboardButton(label, callback_data=f"protondbinfo:{key}:{idx}")]
        )
    return InlineKeyboardMarkup(buttons)


def build_free_games_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("🎮 Epic", callback_data="games:epic"),
            InlineKeyboardButton("🎮 Steam", callback_data="games:steam"),
        ],
        [
            InlineKeyboardButton("🎮 GOG", callback_data="games:gog"),
            InlineKeyboardButton("🎮 Humble", callback_data="games:humble"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


async def handle_callback_query(update, context) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data

    if not allowed(update):
        await _safe_edit_message_text(query, "⛔ Not authorized")
        return

    try:
        if data.startswith("dlogs:page:"):
            payload = _parse_log_page_payload(data, "dlogs:page:")
            if payload:
                container, start, since = payload
                await _handle_dlogs_page(
                    query, context, container, start, since=since, refresh=False
                )
        elif data.startswith("dlogs:refresh:"):
            payload = _parse_log_page_payload(data, "dlogs:refresh:")
            if payload:
                container, start, since = payload
                await _handle_dlogs_page(
                    query, context, container, start, since=since, refresh=True
                )
        elif data.startswith("dlogs:"):
            container = data[6:]
            await _handle_dlogs_callback(query, context, container)
        elif data.startswith("dhealth:"):
            container = data[8:]
            await _handle_dhealth_callback(query, context, container)
        elif data.startswith("dstats:"):
            container = data[7:]
            await _handle_dstats_callback(query, context, container)
        elif data == "docker:refresh":
            await _handle_docker_refresh(query, context, 0)
        elif data.startswith("docker:refresh:"):
            page = _parse_page(data, "docker:refresh:")
            await _handle_docker_refresh(query, context, page)
        elif data.startswith("docker:page:"):
            page = _parse_page(data, "docker:page:")
            await _handle_docker_page(query, context, page)
        elif data == "docker:noop":
            return
        elif data.startswith("tstop:"):
            torrent_hash = data[6:]
            await _handle_torrent_stop(query, context, torrent_hash)
        elif data.startswith("tstart:"):
            torrent_hash = data[7:]
            await _handle_torrent_start(query, context, torrent_hash)
        elif data.startswith("tinfo:"):
            torrent_hash = data[6:]
            await _handle_torrent_info(query, context, torrent_hash)
        elif data == "torrent:refresh":
            await _handle_torrent_refresh(query, context)
        elif data.startswith("games:"):
            game_type = data[6:]
            await _handle_games_callback(query, game_type)
        elif data.startswith("pbmagnet:"):
            key = data[len("pbmagnet:") :]
            await _handle_piratebay_magnet(query, context, key)
        elif data.startswith("tmdbpage:"):
            await _handle_tmdb_page(query, context, data)
        elif data.startswith("tmdbinfo:"):
            await _handle_tmdb_info(query, context, data)
        elif data.startswith("protondbinfo:"):
            await _handle_protondb_info(query, context, data)
        else:
            await _safe_edit_message_text(query, "❓ Unknown action")
    except Exception as e:
        logger.exception("Callback query error")
        try:
            await query.message.reply_text(f"❌ Error: {html.escape(str(e))}")
        except Exception as notify_error:
            logger.error(f"Failed to send error notification: {notify_error}")


async def _handle_dlogs_callback(query, context, container: str) -> None:
    state: BotState = get_state(context.application)
    await state.maybe_refresh("containers")
    if state.get_cached("containers") and container not in state.get_cached(
        "containers"
    ):
        await query.message.reply_text(f"❌ Unknown container: {container}")
        return
    lines = await _get_log_lines(state, container, refresh=True)
    start = max(len(lines) - LOG_PAGE_SIZE, 0)
    msg, keyboard, _ = _render_logs_page(container, lines, start)
    await query.message.reply_text(
        msg, parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def _handle_dlogs_page(
    query, context, container: str, start: int, since: int | None, refresh: bool
) -> None:
    state: BotState = get_state(context.application)
    lines = await _get_log_lines(state, container, refresh=refresh, since=since)
    msg, keyboard, _ = _render_logs_page(container, lines, start, since=since)
    await _safe_edit_message_text(
        query, msg[:4000], parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def _handle_dhealth_callback(query, context, container: str) -> None:
    state: BotState = get_state(context.application)
    await state.maybe_refresh("containers")
    if state.get_cached("containers") and container not in state.get_cached(
        "containers"
    ):
        await query.message.reply_text(f"❌ Unknown container: {container}")
        return
    msg = await services.healthcheck_container(container)
    await query.message.reply_text(f"<pre>{msg}</pre>", parse_mode=ParseMode.HTML)


async def _handle_dstats_callback(query, context, container: str) -> None:
    state: BotState = get_state(context.application)
    await state.maybe_refresh("containers")
    if state.get_cached("containers") and container not in state.get_cached(
        "containers"
    ):
        await query.message.reply_text(f"❌ Unknown container: {container}")
        return
    # We fetch all stats and filter? Or just show all?
    # Original logic showed all for dstats command but filtered for button?
    # Original: "Filter to show only the requested container if possible" -> comment only
    # Actually utils.container_stats_summary returns string for ALL containers.
    # To filter we would need the rich dict.

    stats = await services.container_stats_rich()
    # Filter for container
    target_stats = [s for s in stats if s["name"] == container]
    if not target_stats:
        msg = f"Stats for {container} not found."
    else:
        msg = view.render_container_stats(target_stats)

    await query.message.reply_text(msg, parse_mode=ParseMode.HTML)


def _parse_tmdb_page_payload(data: str) -> tuple[str, int] | None:
    payload = data[len("tmdbpage:") :]
    parts = payload.split(":")
    if len(parts) != 2:
        return None
    key = parts[0]
    try:
        page = int(parts[1])
    except ValueError:
        return None
    return key, max(1, page)


async def _handle_tmdb_page(query, context, data: str) -> None:
    payload = _parse_tmdb_page_payload(data)
    if not payload:
        await query.message.reply_text("❌ Invalid TMDB page request.")
        return
    key, page = payload
    state: BotState = get_state(context.application)
    entry = state.get_tmdb_results(key)
    if not entry:
        await query.message.reply_text("❌ TMDB results expired. Re-run command.")
        return

    try:
        if entry.kind == "movies":
            data = await services.tmdb_trending_movies(page)
            items = tmdb.extract_items(data, default_type="movie")
        elif entry.kind == "shows":
            data = await services.tmdb_trending_shows(page)
            items = tmdb.extract_items(data, default_type="tv")
        elif entry.kind == "incinema":
            data = await services.tmdb_in_cinema(page)
            items = tmdb.extract_items(data, default_type="movie")
        elif entry.kind == "search":
            data = await services.tmdb_search_multi(entry.query or "", page)
            items = tmdb.extract_items(data)
        else:
            await query.message.reply_text("❌ Unsupported TMDB list.")
            return
    except Exception as exc:
        await query.message.reply_text(f"❌ TMDB error: {html.escape(str(exc))}")
        return

    total_pages = int(data.get("total_pages") or 1)
    entry.page = page
    entry.total_pages = total_pages
    entry.items = items
    entry.updated_at = time.monotonic()
    state.tmdb_cache[key] = entry

    title = "TMDB"
    if entry.kind == "movies":
        title = "TMDB Trending Movies"
    elif entry.kind == "shows":
        title = "TMDB Trending Shows"
    elif entry.kind == "incinema":
        title = "TMDB In Cinemas"
    elif entry.kind == "search":
        title = f"TMDB Search: {entry.query}"
    msg = view.render_tmdb_list(title, items)
    keyboard = build_tmdb_keyboard(key, items, page, total_pages)
    await _safe_edit_message_text(
        query, msg[:4000], parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def _handle_tmdb_info(query, context, data: str) -> None:
    payload = data[len("tmdbinfo:") :]
    parts = payload.split(":")
    if len(parts) != 2:
        await query.message.reply_text("❌ Invalid TMDB info request.")
        return
    media_type, id_str = parts
    try:
        tmdb_id = int(id_str)
    except ValueError:
        await query.message.reply_text("❌ Invalid TMDB id.")
        return
    try:
        if media_type == "movie":
            info = await services.tmdb_movie_details(tmdb_id)
        elif media_type == "tv":
            info = await services.tmdb_tv_details(tmdb_id)
        else:
            await query.message.reply_text("❌ Unknown TMDB media type.")
            return
    except Exception as exc:
        await query.message.reply_text(f"❌ TMDB error: {html.escape(str(exc))}")
        return

    title = info.get("title") or info.get("name") or "Unknown"
    overview = info.get("overview") or ""
    rating = info.get("vote_average")
    date = info.get("release_date") or info.get("first_air_date") or ""
    genres = ", ".join(g.get("name") for g in info.get("genres", []) if g.get("name"))
    poster_path = info.get("poster_path")
    url = (
        f"https://www.themoviedb.org/movie/{tmdb_id}"
        if media_type == "movie"
        else f"https://www.themoviedb.org/tv/{tmdb_id}"
    )
    lines = [
        f"<b>{html.escape(str(title))}</b>",
        f"Date: {html.escape(str(date))}" if date else "Date: -",
        f"Rating: {rating:.1f}" if isinstance(rating, (int, float)) else "Rating: -",
        f"Genres: {html.escape(genres) if genres else '-'}",
    ]
    if overview:
        lines.append("")
        # Truncate overview for caption (Telegram limit is 1024 chars)
        max_overview = 600
        if len(overview) > max_overview:
            overview = overview[:max_overview].rsplit(" ", 1)[0] + "..."
        lines.append(html.escape(str(overview)))
    lines.append("")
    lines.append(f'<a href="{url}">TMDB</a>')
    caption = "\n".join(lines)

    # Try to send with poster image, fall back to text on failure
    if poster_path:
        image_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
        try:
            await query.message.reply_photo(
                photo=image_url,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
            return
        except Exception as img_err:
            logger.debug("Failed to send TMDB poster image: %s", img_err)

    # Fallback: text only
    await query.message.reply_text(
        caption, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


async def _handle_protondb_info(query, context, data: str) -> None:
    payload = data[len("protondbinfo:") :]
    parts = payload.split(":")
    if len(parts) != 2:
        await query.message.reply_text("❌ Invalid ProtonDB request.")
        return
    key, idx_str = parts
    try:
        idx = int(idx_str)
    except ValueError:
        await query.message.reply_text("❌ Invalid game index.")
        return

    state: BotState = get_state(context.application)
    games = state.get_protondb_results(key)
    if not games or idx >= len(games):
        await query.message.reply_text("❌ Results expired. Please search again.")
        return

    game = games[idx]
    appid = game.get("appid")
    name = game.get("name") or "Unknown"

    if not appid:
        await query.message.reply_text("❌ Invalid game data.")
        return

    # Fetch data in parallel
    protondb_data, steam_data, player_count = await asyncio.gather(
        services.protondb_summary(appid),
        services.steam_app_details(appid),
        services.steam_player_count(appid),
        return_exceptions=True,
    )

    # Handle exceptions
    if isinstance(protondb_data, Exception):
        logger.debug("ProtonDB fetch failed: %s", protondb_data)
        protondb_data = None
    if isinstance(steam_data, Exception):
        logger.debug("Steam details fetch failed: %s", steam_data)
        steam_data = None
    if isinstance(player_count, Exception):
        logger.debug("Steam player count fetch failed: %s", player_count)
        player_count = None

    # Build response
    lines = [f"<b>{html.escape(str(name))}</b>"]

    # ProtonDB tier
    if protondb_data:
        tier = protondb_data.get("tier")
        trending_tier = protondb_data.get("trendingTier")
        confidence = protondb_data.get("confidence")
        total_reports = protondb_data.get("total")
        score = protondb_data.get("score")

        tier_emoji = protondb.tier_emoji(tier)
        tier_text = protondb.format_tier(tier)
        lines.append(f"ProtonDB: {tier_emoji} <b>{tier_text}</b>")

        if trending_tier and trending_tier != tier:
            trend_emoji = protondb.tier_emoji(trending_tier)
            trend_text = protondb.format_tier(trending_tier)
            lines.append(f"Trending: {trend_emoji} {trend_text}")

        if confidence:
            lines.append(f"Confidence: {html.escape(str(confidence))}")
        if total_reports:
            lines.append(f"Reports: {total_reports}")
        if score is not None:
            lines.append(f"Score: {score:.2f}")
    else:
        lines.append("ProtonDB: <i>No data available</i>")

    # Player count
    if player_count is not None:
        lines.append(f"Current Players: {player_count:,}")

    # Steam details
    metacritic = None
    header_image = None
    if steam_data:
        metacritic = steam_data.get("metacritic", {}).get("score")
        header_image = steam_data.get("header_image")
        release_date = steam_data.get("release_date", {}).get("date")
        genres = steam_data.get("genres", [])
        genre_names = ", ".join(g.get("name", "") for g in genres[:3] if g.get("name"))

        if release_date:
            lines.append(f"Released: {html.escape(str(release_date))}")
        if genre_names:
            lines.append(f"Genres: {html.escape(genre_names)}")
        if metacritic:
            lines.append(f"Metacritic: {metacritic}")

    # Links
    lines.append("")
    lines.append(
        f'<a href="https://www.protondb.com/app/{appid}">ProtonDB</a> | '
        f'<a href="https://store.steampowered.com/app/{appid}">Steam</a>'
    )

    caption = "\n".join(lines)

    # Try to send with image
    if header_image:
        try:
            await query.message.reply_photo(
                photo=header_image,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
            return
        except Exception as img_err:
            logger.debug("Failed to send Steam header image: %s", img_err)

    # Fallback: text only
    await query.message.reply_text(
        caption, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


async def _handle_docker_refresh(query, context, page: int) -> None:
    await _update_docker_message(query, context, page=page, refresh=True)


def _parse_page(data: str, prefix: str) -> int:
    token = data[len(prefix) :].strip()
    try:
        return max(int(token), 0)
    except ValueError:
        return 0


async def _update_docker_message(query, context, page: int, refresh: bool) -> None:
    state: BotState = get_state(context.application)
    if refresh:
        await state.refresh_containers()
    else:
        await state.maybe_refresh("containers")

    containers = await services.list_containers()
    containers_sorted = sorted(containers, key=lambda item: str(item.get("name", "")))
    page, total_pages = normalize_docker_page(len(containers_sorted), page)
    start = page * DOCKER_PAGE_SIZE
    end = start + DOCKER_PAGE_SIZE
    page_containers = containers_sorted[start:end]
    msg = view.render_container_list_page(page_containers, page, total_pages)

    container_names = [c.get("name", "") for c in containers_sorted if c.get("name")]
    keyboard = build_docker_keyboard(container_names, page=page)

    await _safe_edit_message_text(
        query, msg[:4000], parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def _handle_docker_page(query, context, page: int) -> None:
    await _update_docker_message(query, context, page=page, refresh=False)


async def _handle_torrent_stop(query, context, torrent_hash: str) -> None:
    if not await _validate_torrent_hash(context, torrent_hash):
        await query.message.reply_text("❌ Unknown torrent.")
        return
    result = await services.torrent_stop_by_hash(torrent_hash)
    await query.message.reply_text(result, parse_mode=ParseMode.HTML)


async def _handle_torrent_start(query, context, torrent_hash: str) -> None:
    if not await _validate_torrent_hash(context, torrent_hash):
        await query.message.reply_text("❌ Unknown torrent.")
        return
    result = await services.torrent_start_by_hash(torrent_hash)
    await query.message.reply_text(result, parse_mode=ParseMode.HTML)


async def _handle_torrent_info(query, context, torrent_hash: str) -> None:
    if not await _validate_torrent_hash(context, torrent_hash):
        await query.message.reply_text("❌ Unknown torrent.")
        return
    result = await services.torrent_info_by_hash(torrent_hash)
    await query.message.reply_text(result, parse_mode=ParseMode.HTML)


async def _handle_torrent_refresh(query, context) -> None:
    state: BotState = get_state(context.application)
    await state.refresh_torrents()

    torrents = await services.get_torrent_list()
    msg = view.render_torrent_list(torrents)
    keyboard = build_torrent_keyboard(torrents)

    await _safe_edit_message_text(
        query, msg[:4000], parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def _validate_torrent_hash(context, torrent_hash: str) -> bool:
    state: BotState = get_state(context.application)
    await state.maybe_refresh("torrents")
    torrents = await services.get_torrent_list()
    return any(
        (t.get("hash") or "").startswith(torrent_hash)
        for t in torrents
        if t.get("hash")
    )


async def _handle_games_callback(query, game_type: str) -> None:
    from .. import scheduled as scheduled_fetchers

    await query.message.reply_text(f"🔄 Fetching {game_type} free games...")

    # scheduled fetchers are likely sync, so we wrap them
    if game_type == "epic":
        message, image_urls = await asyncio.to_thread(
            scheduled_fetchers.fetch_epic_free_games
        )
    elif game_type == "steam":
        message = await asyncio.to_thread(scheduled_fetchers.fetch_steam_free_games, 5)
        image_urls = []
    elif game_type == "gog":
        message, image_urls = await asyncio.to_thread(
            scheduled_fetchers.fetch_gog_free_games
        )
    elif game_type == "humble":
        message, image_urls = await asyncio.to_thread(
            scheduled_fetchers.fetch_humble_free_games
        )
    else:
        await query.message.reply_text("❓ Unknown game store")
        return

    if image_urls:
        await query.message.reply_photo(
            photo=image_urls[0],
            caption=message,
            parse_mode=ParseMode.HTML,
        )
    else:
        await query.message.reply_text(
            message, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )


async def _handle_piratebay_magnet(query, context, key: str) -> None:
    state: BotState = get_state(context.application)
    entry = state.get_magnet(key)
    if not entry:
        await query.message.reply_text("❌ Torrent link expired.")
        return
    name, magnet = entry
    safe_name = html.escape(name)
    safe_magnet = html.escape(magnet)
    msg = f"<b>{safe_name}</b>\n<code>{safe_magnet}</code>"
    await query.message.reply_text(msg, parse_mode=ParseMode.HTML)
