from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

import httpx
import pytest

from zalobot import AsyncBot, AsyncContext, Bot, Context, Dispatcher, F, Router, Text, Update, errors
from zalobot.dispatcher import WebhookActiveError
from zalobot.testing import FakeZalo

from .conftest import TOKEN


def _update(fake: FakeZalo, event: dict[str, Any]) -> Update:
    fake.updates.remove(event)
    return Update.from_dict(event)


# --- filters -------------------------------------------------------------------------------------------------


def test_filters(fake: FakeZalo) -> None:
    text = _update(fake, fake.push_text("/Add 50k cà phê", chat_id="c1", user_id="u1"))
    group = _update(fake, fake.push_text("hi @bot", chat_id="g1", chat_type="GROUP"))
    photo = _update(fake, fake.push_photo(caption="hóa đơn 120k"))
    sticker = _update(fake, fake.push_sticker())
    voice = _update(fake, fake.push_voice())
    unsupported = _update(fake, fake.push_unsupported())
    assert F.text(text) and not F.text(photo)
    assert F.photo(photo) and F.sticker(sticker) and F.voice(voice) and F.unsupported(unsupported)
    assert F.private(text) and not F.private(group) and F.group(group)
    assert F.command("add")(text) and F.command("/ADD")(text) and not F.command("start")(text)
    assert F.command()(text) and not F.command()(group)
    assert F.regex(r"\d+k")(text) and F.regex(r"\d+k")(photo) and not F.regex(r"\d+k")(sticker)
    assert F.from_user("u1")(text) and not F.from_user("u2")(text)
    assert F.chat("c1")(text) and not F.chat("c1")(group)
    combined = (F.text & F.private) | F.photo
    assert combined(text) and combined(photo) and not combined(group)
    assert (~F.text)(photo) and not (~F.text)(text)
    assert "text" in repr(F.text & F.private)
    assert F.all(Update.from_dict({"event_name": "x"}))
    assert not F.private(Update.from_dict({"event_name": "x"}))


def test_update_command_parsing(fake: FakeZalo) -> None:
    u = _update(fake, fake.push_text("/add   50k  cà phê"))
    assert (u.command, u.args) == ("add", "50k  cà phê")
    for text, expected in [("/", (None, "")), ("hello", (None, "")), ("/start", ("start", ""))]:
        assert _update(fake, fake.push_text(text)).command == expected[0]
    assert Update.from_dict({"event_name": "x"}).command is None


# --- routing (blocking) --------------------------------------------------------------------------------------


def test_first_match_wins_and_reply_helpers(fake: FakeZalo) -> None:
    dp = Dispatcher()
    seen: list[str] = []

    @dp.command("start")
    def start(ctx: Context) -> None:
        seen.append("start")
        ctx.typing()
        ctx.reply_text(Text().bold("Xin chào ").plain(ctx.message.from_user.display_name))
        ctx.reply_photo("https://e.com/a.jpg", caption="menu")
        ctx.reply_sticker("abc")
        ctx.reply_voice("https://e.com/v.aac")
        ctx.reply_long("x\n" * 1500)

    @dp.message(F.text)
    def any_text(ctx: Context) -> None:
        seen.append(f"text:{ctx.text}")

    @dp.message(F.text)
    def never(ctx: Context) -> None:
        seen.append("never")

    with fake.bot() as bot:
        assert dp.feed(bot, _update(fake, fake.push_text("/START now")))
        assert dp.feed(bot, _update(fake, fake.push_text("ăn trưa")))
        assert not dp.feed(bot, _update(fake, fake.push_sticker()))
    assert seen == ["start", "text:ăn trưa"]
    assert [r.method for r in fake.sent] == [
        "sendChatAction",
        "sendMessage",
        "sendPhoto",
        "sendSticker",
        "sendVoice",
        "sendMessage",
        "sendMessage",
    ]
    assert fake.sent[1].fields["text"] == "Xin chào Ted"


def test_context_fields(fake: FakeZalo) -> None:
    dp = Dispatcher()
    got: dict[str, Any] = {}

    @dp.command("add")
    def add(ctx: Context) -> None:
        got.update(chat=ctx.chat_id, user=ctx.user_id, cmd=ctx.command, args=ctx.args, text=ctx.text)

    with fake.bot() as bot:
        dp.feed(bot, _update(fake, fake.push_text("/add 50k", chat_id="c9", user_id="u9")))
    assert got == {"chat": "c9", "user": "u9", "cmd": "add", "args": "50k", "text": "/add 50k"}
    with pytest.raises(AttributeError):
        _ = Context(Update.from_dict({"event_name": "x"}), Bot(TOKEN)).message


def test_fallback_children_and_dedupe(fake: FakeZalo) -> None:
    dp = Dispatcher(dedupe_size=2)
    child = Router("child")
    dp.include(child)
    calls: list[str] = []
    child.message(F.photo)(lambda ctx: calls.append("photo"))
    dp.fallback(lambda ctx: calls.append("fallback"))
    with fake.bot() as bot:
        event = fake.push_photo()
        update = _update(fake, event)
        assert dp.feed(bot, update)
        assert not dp.feed(bot, update)  # the same message id again
        dp.feed(bot, _update(fake, fake.push_voice()))
        dp.feed(bot, _update(fake, fake.push_voice()))
        assert dp.feed(bot, update)  # pushed out of the 2-id window
        assert dp.feed(bot, Update.from_dict({"event_name": "x"}))  # no message id: never deduped
    assert calls == ["photo", "fallback", "fallback", "photo", "fallback"]
    with pytest.raises(ValueError):
        dp.include(dp)
    with pytest.raises(ValueError):
        dp.command()


def test_error_hooks(fake: FakeZalo, caplog: pytest.LogCaptureFixture) -> None:
    dp = Dispatcher()
    child = dp.include(Router())
    errors_seen: list[str] = []

    @dp.message(F.text)
    def boom(ctx: Context) -> None:
        raise RuntimeError("root boom")

    @child.message(F.photo)
    def child_boom(ctx: Context) -> None:
        raise RuntimeError("child boom")

    @child.error
    def on_child_error(ctx: Context, exc: Exception) -> None:
        errors_seen.append(f"child:{exc}")

    with fake.bot() as bot:
        dp.feed(bot, _update(fake, fake.push_text("x")))  # no root hook: logged
        dp.feed(bot, _update(fake, fake.push_photo()))
        dp.error(lambda ctx, exc: (_ for _ in ()).throw(ValueError("hook broke")))
        dp.feed(bot, _update(fake, fake.push_text("y")))
    assert errors_seen == ["child:child boom"]
    assert "handler failed" in caplog.text and "root boom" in caplog.text
    assert "error handler failed" in caplog.text


def test_async_handler_with_blocking_bot_is_an_error(fake: FakeZalo) -> None:
    dp = Dispatcher()

    @dp.message()
    async def handler(ctx: AsyncContext) -> None: ...

    with fake.bot() as bot, pytest.raises(TypeError, match="AsyncBot"):
        dp.feed(bot, _update(fake, fake.push_text("x")))


# --- routing (async) -----------------------------------------------------------------------------------------


async def test_async_and_plain_handlers_under_asyncbot(fake: FakeZalo) -> None:
    dp = Dispatcher()
    threads: list[str] = []

    @dp.command("a")
    async def async_handler(ctx: AsyncContext) -> None:
        await ctx.typing()
        await ctx.reply_text("async", parse_mode="markdown")
        await ctx.reply_photo("https://e.com/p.jpg")
        await ctx.reply_sticker("s")
        await ctx.reply_voice("https://e.com/v.aac")
        await ctx.reply_long("y\n" * 1500)

    @dp.command("p")
    def plain_handler(ctx: Context) -> None:
        threads.append(threading.current_thread().name)
        ctx.reply_text("plain")
        ctx.reply_long("z")
        ctx.reply_photo("https://e.com/p.jpg")
        ctx.reply_sticker("s")
        ctx.reply_voice("https://e.com/v.aac")
        ctx.typing()

    async with fake.async_bot() as bot:
        assert await dp.feed_async(bot, _update(fake, fake.push_text("/a")))
        assert await dp.feed_async(bot, _update(fake, fake.push_text("/p")))
        assert not await dp.feed_async(bot, _update(fake, fake.push_text("other")))
    texts = [r.text for r in fake.sent if r.method == "sendMessage"]
    assert texts[0] == "async" and "plain" in texts and "z" in texts
    assert threads and threads[0] != threading.main_thread().name


async def test_async_error_hooks(fake: FakeZalo, caplog: pytest.LogCaptureFixture) -> None:
    dp = Dispatcher()
    seen: list[str] = []

    @dp.message(F.text)
    async def boom(ctx: AsyncContext) -> None:
        raise RuntimeError("async boom")

    @dp.message(F.photo)
    def plain_boom(ctx: Context) -> None:
        raise RuntimeError("plain boom")

    async with fake.async_bot() as bot:
        await dp.feed_async(bot, _update(fake, fake.push_text("x")))  # logged

        @dp.error
        async def on_error(ctx: Any, exc: Exception) -> None:
            seen.append(str(exc))

        await dp.feed_async(bot, _update(fake, fake.push_text("y")))
        await dp.feed_async(bot, _update(fake, fake.push_photo()))
        dp.error(lambda ctx, exc: 1 / 0)
        await dp.feed_async(bot, _update(fake, fake.push_text("z")))
        assert not await dp.feed_async(bot, Update.from_dict({"event_name": "x"}))
    assert seen == ["async boom", "plain boom"]
    assert "async boom" in caplog.text and "error handler failed" in caplog.text


# --- polling (blocking) --------------------------------------------------------------------------------------


def test_run_polling_handles_then_stops(fake: FakeZalo) -> None:
    dp = Dispatcher()
    got: list[str] = []

    @dp.message(F.text)
    def echo(ctx: Context) -> None:
        got.append(ctx.text or "")
        ctx.reply_text(ctx.text or "")
        if len(got) == 3:
            dp.stop()

    for word in ["một", "hai", "ba", "bốn"]:
        fake.push_text(word)
    with fake.bot() as bot:
        dp.run_polling(bot, timeout=1)
    assert got == ["một", "hai", "ba"]
    assert [r.text for r in fake.sent] == got
    assert len(fake.updates) == 1


def test_run_polling_dedupes_repeats(fake: FakeZalo) -> None:
    dp = Dispatcher()
    got: list[str] = []
    event = fake.push_text("once")
    fake.updates.append(event)
    fake.push_text("last")

    @dp.message(F.text)
    def handler(ctx: Context) -> None:
        got.append(ctx.text or "")
        if ctx.text == "last":
            dp.stop()

    with fake.bot() as bot:
        dp.run_polling(bot)
    assert got == ["once", "last"]


def test_run_polling_backs_off_and_recovers(fake: FakeZalo, caplog: pytest.LogCaptureFixture) -> None:
    dp = Dispatcher()
    dp.message()(lambda ctx: dp.stop())
    fake.fail(429, method="getUpdates", times=2)
    fake.fail(500, method="getUpdates")
    fake.push_text("hi")
    with fake.bot() as bot:
        dp.run_polling(bot, backoff_start=0.001, backoff_max=0.004)
    assert [m for m, _ in fake.calls].count("getUpdates") == 4
    assert caplog.text.count("getUpdates failed") == 3


def test_run_polling_network_errors_back_off(caplog: pytest.LogCaptureFixture) -> None:
    dp = Dispatcher()
    calls = []

    def flaky(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("getWebhookInfo"):
            return httpx.Response(200, json={"ok": True, "result": {"url": ""}})
        if len(calls) < 3:
            raise httpx.ConnectError("down")
        dp.stop()
        return httpx.Response(408, json={"ok": False, "error_code": 408, "description": "timeout"})

    with Bot(TOKEN, transport=httpx.MockTransport(flaky)) as bot:
        dp.run_polling(bot, backoff_start=0.001)
    assert "ConnectError" in caplog.text


def test_run_polling_stops_on_dead_token(fake: FakeZalo) -> None:
    dp = Dispatcher()
    fake.fail(401, method="getUpdates")
    with fake.bot() as bot, pytest.raises(errors.Unauthorized):
        dp.run_polling(bot)


def test_run_polling_refuses_with_webhook(fake: FakeZalo) -> None:
    dp = Dispatcher()
    fake.webhook_url = "https://example.com/hook"
    with fake.bot() as bot:
        with pytest.raises(WebhookActiveError, match="delete_webhook"):
            dp.run_polling(bot)
        fake.webhook_url = ""
        dp.message()(lambda ctx: dp.stop())
        fake.push_text("x")
        dp.run_polling(bot, check_webhook=False)
    assert [m for m, _ in fake.calls].count("getWebhookInfo") == 1


def test_run_polling_ctrl_c(fake: FakeZalo, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="zalobot")
    dp = Dispatcher()

    @dp.message()
    def interrupt(ctx: Context) -> None:
        raise KeyboardInterrupt

    fake.push_text("x")
    with fake.bot() as bot:
        dp.run_polling(bot)
    assert "Ctrl-C" in caplog.text


def test_run_polling_type_checks(fake: FakeZalo) -> None:
    dp = Dispatcher()
    with pytest.raises(TypeError, match="start_polling"):
        dp.run_polling(fake.async_bot())  # type: ignore[arg-type]


def test_run_with_blocking_bot(fake: FakeZalo) -> None:
    dp = Dispatcher()
    dp.message()(lambda ctx: dp.stop())
    fake.push_text("x")
    with fake.bot() as bot:
        dp.run(bot)
    assert not fake.updates


# --- polling (async) -----------------------------------------------------------------------------------------


async def test_start_polling(fake: FakeZalo) -> None:
    dp = Dispatcher()
    got: list[str] = []

    @dp.message(F.text)
    async def echo(ctx: AsyncContext) -> None:
        got.append(ctx.text or "")
        await ctx.reply_text(ctx.text or "")
        if len(got) == 2:
            dp.stop()

    fake.push_text("a")
    fake.fail(429, method="getUpdates")
    fake.push_text("b")
    async with fake.async_bot() as bot:
        await dp.start_polling(bot, backoff_start=0.001)
    assert got == ["a", "b"]
    assert [r.text for r in fake.sent] == ["a", "b"]


async def test_stop_cancels_a_hanging_long_poll() -> None:
    dp = Dispatcher()

    async def hang(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("getWebhookInfo"):
            return httpx.Response(200, json={"ok": True, "result": {"url": ""}})
        await asyncio.sleep(60)
        raise AssertionError("not cancelled")

    async with AsyncBot(TOKEN, transport=httpx.MockTransport(hang)) as bot:
        task = asyncio.create_task(dp.start_polling(bot))
        await asyncio.sleep(0.05)
        dp.stop()
        await asyncio.wait_for(task, timeout=2)


async def test_start_polling_errors(fake: FakeZalo) -> None:
    dp = Dispatcher()
    async with fake.async_bot() as bot:
        fake.webhook_url = "https://e.com/h"
        with pytest.raises(WebhookActiveError):
            await dp.start_polling(bot)
        fake.webhook_url = ""
        fake.fail(401, method="getUpdates")
        with pytest.raises(errors.Unauthorized):
            await dp.start_polling(bot)
    with pytest.raises(TypeError, match="run_polling"):
        await dp.start_polling(Bot(TOKEN))  # type: ignore[arg-type]


async def test_stop_during_backoff(fake: FakeZalo) -> None:
    dp = Dispatcher()
    fake.fail(429, method="getUpdates", times=100)
    async with fake.async_bot() as bot:
        task = asyncio.create_task(dp.start_polling(bot, backoff_start=30))
        await asyncio.sleep(0.05)
        dp.stop()
        await asyncio.wait_for(task, timeout=2)


def test_run_with_asyncbot(fake: FakeZalo, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="zalobot")
    dp = Dispatcher()

    @dp.message()
    async def handler(ctx: AsyncContext) -> None:
        dp.stop()

    fake.push_text("x")
    dp.run(fake.async_bot())
    assert "polling stopped" in caplog.text

    @dp.command("quit")
    async def interrupt(ctx: AsyncContext) -> None:
        raise KeyboardInterrupt

    dp2 = Dispatcher()
    dp2.message()(interrupt)
    fake.push_text("/quit")
    dp2.run(fake.async_bot())
    assert "Ctrl-C" in caplog.text
