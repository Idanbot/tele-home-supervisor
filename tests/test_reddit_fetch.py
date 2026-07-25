from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import DummyContext, DummyMessage, DummyUpdate

from tele_home_supervisor.handlers import notifications


async def _allow_guard(update, context) -> bool:
    return True


@pytest.mark.asyncio
async def test_reddit_fetch_without_arguments_shows_curated_subreddits(
    monkeypatch,
) -> None:
    monkeypatch.setattr(notifications, "guard", _allow_guard)
    update = DummyUpdate(chat_id=1, user_id=1)
    update.message.reply_text = AsyncMock()

    await notifications.cmd_reddit_fetch(update, DummyContext())

    reply_markup = update.message.reply_text.await_args.kwargs["reply_markup"]
    buttons = [button for row in reply_markup.inline_keyboard for button in row]
    assert {button.callback_data for button in buttons} == {
        "reddit_fetch:pick:aivideo",
        "reddit_fetch:pick:memes",
        "reddit_fetch:pick:dankmemes",
        "reddit_fetch:pick:art",
        "reddit_fetch:pick:accidentalrenaissance",
        "reddit_fetch:pick:popular",
        "reddit_fetch:pick:news",
    }


@pytest.mark.asyncio
async def test_reddit_fetch_sends_direct_image_post(monkeypatch) -> None:
    monkeypatch.setattr(notifications, "guard", _allow_guard)
    post = {
        "id": "image",
        "title": "A generated scene",
        "subreddit": "aivideo",
        "author": "artist",
        "score": 42,
        "num_comments": 7,
        "permalink": "/r/aivideo/comments/image",
        "url": "https://i.redd.it/example.jpg",
    }
    fetch = AsyncMock(return_value=post)
    monkeypatch.setattr(notifications.reddit_briefing, "fetch_reddit_post", fetch)
    update = DummyUpdate(chat_id=1, user_id=1)
    update.message.reply_photo = AsyncMock()

    await notifications.cmd_reddit_fetch(
        update,
        DummyContext(args=["r/aivideo", "top"]),
    )

    fetch.assert_awaited_once_with("aivideo", "top")
    assert update.message.reply_photo.await_args.kwargs["photo"] == post["url"]
    assert (
        "A generated scene" in update.message.reply_photo.await_args.kwargs["caption"]
    )


@pytest.mark.asyncio
async def test_reddit_fetch_sends_direct_video_post(monkeypatch) -> None:
    monkeypatch.setattr(notifications, "guard", _allow_guard)
    post = {
        "id": "video",
        "title": "Short video",
        "subreddit": "aivideo",
        "author": "creator",
        "score": 9,
        "num_comments": 2,
        "permalink": "/r/aivideo/comments/video",
        "media_url": "https://v.redd.it/example/DASH_720.mp4",
    }
    monkeypatch.setattr(
        notifications.reddit_briefing,
        "fetch_reddit_post",
        AsyncMock(return_value=post),
    )
    update = DummyUpdate(chat_id=1, user_id=1)
    update.message.reply_video = AsyncMock()

    await notifications.cmd_reddit_fetch(
        update,
        DummyContext(args=["aivideo", "random"]),
    )

    assert update.message.reply_video.await_args.kwargs["video"] == post["media_url"]
    assert "Short video" in update.message.reply_video.await_args.kwargs["caption"]


@pytest.mark.asyncio
async def test_reddit_fetch_sends_self_post_as_text(monkeypatch) -> None:
    monkeypatch.setattr(notifications, "guard", _allow_guard)
    post = {
        "id": "text",
        "title": "Discussion",
        "subreddit": "news",
        "author": "reporter",
        "score": 11,
        "num_comments": 4,
        "permalink": "/r/news/comments/text",
        "url": "/r/news/comments/text",
        "selftext": "Context with <markup>",
    }
    monkeypatch.setattr(
        notifications.reddit_briefing,
        "fetch_reddit_post",
        AsyncMock(return_value=post),
    )
    update = DummyUpdate(chat_id=1, user_id=1)
    update.message.reply_text = AsyncMock()

    await notifications.cmd_reddit_fetch(
        update,
        DummyContext(args=["news"]),
    )

    fetch = notifications.reddit_briefing.fetch_reddit_post
    fetch.assert_awaited_once_with("news", "trending")
    text = update.message.reply_text.await_args.args[0]
    assert "Discussion" in text
    assert "Context with &lt;markup&gt;" in text


@pytest.mark.asyncio
async def test_reddit_fetch_subreddit_callback_shows_mode_keyboard() -> None:
    query = SimpleNamespace(
        data="reddit_fetch:pick:memes",
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=query)

    await notifications.handle_reddit_fetch_callback(update, DummyContext())

    reply_markup = query.edit_message_text.await_args.kwargs["reply_markup"]
    buttons = [button for row in reply_markup.inline_keyboard for button in row]
    assert {button.callback_data for button in buttons} == {
        "reddit_fetch:run:memes:trending",
        "reddit_fetch:run:memes:random",
        "reddit_fetch:run:memes:top",
    }


@pytest.mark.asyncio
async def test_reddit_fetch_mode_callback_fetches_selected_post(monkeypatch) -> None:
    post = {
        "id": "selected",
        "title": "Selected post",
        "subreddit": "art",
        "author": "painter",
        "score": 6,
        "num_comments": 1,
        "permalink": "/r/art/comments/selected",
        "url": "https://example.com/article",
    }
    fetch = AsyncMock(return_value=post)
    monkeypatch.setattr(notifications.reddit_briefing, "fetch_reddit_post", fetch)
    message = DummyMessage()
    message.reply_text = AsyncMock()
    query = SimpleNamespace(
        data="reddit_fetch:run:art:top",
        edit_message_text=AsyncMock(),
        message=message,
    )
    update = SimpleNamespace(callback_query=query)

    await notifications.handle_reddit_fetch_callback(update, DummyContext())

    fetch.assert_awaited_once_with("art", "top")
    assert "Selected post" in message.reply_text.await_args.args[0]
