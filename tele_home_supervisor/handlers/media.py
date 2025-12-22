"""Media command handlers (IMDB)."""

from __future__ import annotations

import html

from telegram.constants import ParseMode

from .. import services
from .common import guard, get_state_and_recorder, record_error


def _fmt_imdb(details: dict[str, object]) -> str:
    title = html.escape(str(details.get("title", "Unknown")))
    url = html.escape(str(details.get("url", "")))
    description = html.escape(str(details.get("description", "")))
    genres = ", ".join(str(g) for g in details.get("genres", []) if g) or "-"
    content_rating = html.escape(str(details.get("content_rating", ""))) or "-"
    runtime = html.escape(str(details.get("runtime", ""))) or "-"
    rating = details.get("rating")
    rating_count = details.get("rating_count")
    release = html.escape(str(details.get("release", ""))) or "-"
    cast = details.get("cast", [])
    cast_line = ", ".join(html.escape(str(c)) for c in cast if c) or "-"
    rating_line = "-"
    if rating:
        rating_line = str(rating)
        if rating_count:
            rating_line = f"{rating_line} ({rating_count} votes)"

    lines = [
        f"<b>{title}</b>",
        f"Release: {release}",
        f"Rating: {rating_line}",
        f"Genres: {html.escape(genres)}",
        f"Runtime: {runtime}",
        f"Content: {content_rating}",
        f"Cast: {cast_line}",
    ]
    if description:
        lines.append("")
        lines.append(description)
    if url:
        lines.append("")
        lines.append(f'<a href="{url}">IMDB</a>')
    return "\n".join(lines)


def _fmt_list(title: str, rows: list[dict[str, object]], with_scores: bool) -> str:
    lines = [f"<b>{html.escape(title)}</b>"]
    for idx, row in enumerate(rows, start=1):
        name = html.escape(str(row.get("title", "Unknown")))
        year = html.escape(str(row.get("year", ""))).strip()
        suffix = f" ({year})" if year else ""
        if with_scores:
            tom = row.get("tomatometer")
            aud = row.get("audience")
            score = "-"
            if tom is not None:
                score = f"{tom}%"
                if aud is not None:
                    score = f"{score} / {aud}%"
            lines.append(f"{idx}. {name}{suffix} - {score}")
        else:
            lines.append(f"{idx}. {name}{suffix}")
    return "\n".join(lines)


async def cmd_imdb(update, context) -> None:
    if not await guard(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /imdb <query>")
        return
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("Usage: /imdb <query>")
        return
    try:
        _, recorder = get_state_and_recorder(context)
        debug_sink = recorder.capture("imdb", "imdb fetch failed")
        details = await services.imdb_details(query, debug_sink=debug_sink)
    except Exception as e:
        await record_error(
            recorder,
            "imdb",
            f"imdb failed for query: {query}",
            e,
            update.message.reply_text,
        )
        return
    if not details:
        await update.message.reply_text("No results found.")
        return
    msg = _fmt_imdb(details)
    await update.message.reply_text(
        msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


async def cmd_imdbmovies(update, context) -> None:
    if not await guard(update, context):
        return
    try:
        _, recorder = get_state_and_recorder(context)
        debug_sink = recorder.capture("imdbmovies", "imdb trending fetch failed")
        rows = await services.imdb_trending("movies", debug_sink=debug_sink)
    except Exception as e:
        await record_error(
            recorder,
            "imdbmovies",
            "imdb trending movies failed",
            e,
            update.message.reply_text,
        )
        return
    if not rows:
        await update.message.reply_text("No results found.")
        return
    msg = _fmt_list("IMDB Trending Movies", rows, with_scores=False)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_imdbshows(update, context) -> None:
    if not await guard(update, context):
        return
    try:
        _, recorder = get_state_and_recorder(context)
        debug_sink = recorder.capture("imdbshows", "imdb trending fetch failed")
        rows = await services.imdb_trending("shows", debug_sink=debug_sink)
    except Exception as e:
        await record_error(
            recorder,
            "imdbshows",
            "imdb trending shows failed",
            e,
            update.message.reply_text,
        )
        return
    if not rows:
        await update.message.reply_text("No results found.")
        return
    msg = _fmt_list("IMDB Trending Shows", rows, with_scores=False)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
