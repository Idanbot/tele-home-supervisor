"""Media command handlers (TMDB)."""

from __future__ import annotations

from telegram.constants import ParseMode

from .. import services, tmdb, view
from .callbacks import build_tmdb_keyboard
from .common import guard, get_state_and_recorder, record_error


async def cmd_movies(update, context) -> None:
    if not await guard(update, context):
        return
    state, recorder = get_state_and_recorder(context)
    try:
        data = await services.tmdb_trending_movies()
    except Exception as e:
        await record_error(
            recorder,
            "movies",
            "tmdb trending movies failed",
            e,
            update.message.reply_text,
        )
        return
    items = tmdb.extract_items(data, default_type="movie")
    if not items:
        await update.message.reply_text("No results found.")
        return
    total_pages = int(data.get("total_pages") or 1)
    key = state.new_tmdb_key()
    state.store_tmdb_results(
        key, "movies", None, page=1, total_pages=total_pages, items=items
    )
    msg = view.render_tmdb_list("TMDB Trending Movies", items)
    keyboard = build_tmdb_keyboard(key, items, 1, total_pages)
    await update.message.reply_text(
        msg, parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def cmd_shows(update, context) -> None:
    if not await guard(update, context):
        return
    state, recorder = get_state_and_recorder(context)
    try:
        data = await services.tmdb_trending_shows()
    except Exception as e:
        await record_error(
            recorder,
            "shows",
            "tmdb trending shows failed",
            e,
            update.message.reply_text,
        )
        return
    items = tmdb.extract_items(data, default_type="tv")
    if not items:
        await update.message.reply_text("No results found.")
        return
    total_pages = int(data.get("total_pages") or 1)
    key = state.new_tmdb_key()
    state.store_tmdb_results(
        key, "shows", None, page=1, total_pages=total_pages, items=items
    )
    msg = view.render_tmdb_list("TMDB Trending Shows", items)
    keyboard = build_tmdb_keyboard(key, items, 1, total_pages)
    await update.message.reply_text(
        msg, parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def cmd_incinema(update, context) -> None:
    if not await guard(update, context):
        return
    state, recorder = get_state_and_recorder(context)
    try:
        data = await services.tmdb_in_cinema()
    except Exception as e:
        await record_error(
            recorder,
            "incinema",
            "tmdb in cinema failed",
            e,
            update.message.reply_text,
        )
        return
    items = tmdb.extract_items(data, default_type="movie")
    if not items:
        await update.message.reply_text("No results found.")
        return
    total_pages = int(data.get("total_pages") or 1)
    key = state.new_tmdb_key()
    state.store_tmdb_results(
        key, "incinema", None, page=1, total_pages=total_pages, items=items
    )
    msg = view.render_tmdb_list("TMDB In Cinemas", items)
    keyboard = build_tmdb_keyboard(key, items, 1, total_pages)
    await update.message.reply_text(
        msg, parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def cmd_tmdb(update, context) -> None:
    if not await guard(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /tmdb <query>")
        return
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("Usage: /tmdb <query>")
        return
    state, recorder = get_state_and_recorder(context)
    try:
        data = await services.tmdb_search_multi(query)
    except Exception as e:
        await record_error(
            recorder,
            "tmdb",
            f"tmdb search failed for query: {query}",
            e,
            update.message.reply_text,
        )
        return
    items = tmdb.extract_items(data)
    if not items:
        await update.message.reply_text("No results found.")
        return
    total_pages = int(data.get("total_pages") or 1)
    key = state.new_tmdb_key()
    state.store_tmdb_results(
        key, "search", query, page=1, total_pages=total_pages, items=items
    )
    msg = view.render_tmdb_list(f"TMDB Search: {query}", items)
    keyboard = build_tmdb_keyboard(key, items, 1, total_pages)
    await update.message.reply_text(
        msg, parse_mode=ParseMode.HTML, reply_markup=keyboard
    )
