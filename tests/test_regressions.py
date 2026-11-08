"""Regression tests: each one failed before its fix."""

from __future__ import annotations

import asyncio
import traceback
from typing import Any

import httpx
import pytest

from zalobot import AsyncBot, AsyncContext, Bot, Context, Dispatcher, F, RetryPolicy, Router, errors, split_text
from zalobot.dispatcher import WebhookActiveError
from zalobot.testing import FakeZalo
from zalobot.text import utf16_len

from .conftest import TOKEN

# --- an error hook that replies, under AsyncBot (it used to freeze the event loop) ---------------------------


@pytest.mark.parametrize("handler_async", [False, True])
@pytest.mark.parametrize("hook_async", [False, True])
async def test_regression_error_hook_can_reply_under_asyncbot(
    fake: FakeZalo, handler_async: bool, hook_async: bool
) -> None:
    dp = Dispatcher()
    if handler_async:

        async def handler(ctx: AsyncContext) -> None:
            raise RuntimeError("boom")
    else:

        def handler(ctx: Context) -> None:  # type: ignore[misc]
            raise RuntimeError("boom")

    if hook_async:

        async def hook(ctx: AsyncContext, exc: Exception) -> None:
            await ctx.reply_text(f"sorry: {exc}")
    else:

        def hook(ctx: Context, exc: Exception) -> None:  # type: ignore[misc]
            ctx.reply_text(f"sorry: {exc}")

    dp.message(F.text)(handler)
    dp.error(hook)
    fake.push_text("x")
    async with fake.async_bot() as bot:
        [update] = await bot.get_updates()
        await dp.feed_async(bot, update)
    assert [r.text for r in fake.sent] == ["sorry: boom"]


async def test_regression_blocking_reply_on_the_loop_thread_raises(fake: FakeZalo) -> None:
    from zalobot.dispatcher import _ThreadBridge

    async with fake.async_bot() as bot:
        bridge = _ThreadBridge(bot, asyncio.get_running_loop())
        with pytest.raises(RuntimeError, match="event loop"):
            bridge.send_message("c", "x")


def test_regression_async_error_hook_with_blocking_bot_is_reported(
    fake: FakeZalo, caplog: pytest.LogCaptureFixture
) -> None:
    dp = Dispatcher()

    @dp.message()
    def handler(ctx: Context) -> None:
        raise RuntimeError("boom")

    @dp.error
    async def hook(ctx: Any, exc: Exception) -> None: ...

    fake.push_text("x")
    with fake.bot() as bot:
        [update] = bot.get_updates()
        dp.feed(bot, update)
    assert "AsyncBot" in caplog.text


# --- the token through the exception chain and frame locals ---------------------------------------------------


def _all_text(exc: BaseException) -> str:
    return "".join(traceback.TracebackException.from_exception(exc, capture_locals=True).format())


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_regression_token_not_in_exception_context_or_locals(asynchronous: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("getMe"):
            raise httpx.ConnectError(f"cannot reach {request.url}")
        return httpx.Response(400, json={"ok": False, "error_code": 400, "description": "bad"})

    caught: list[errors.ZaloError] = []
    if asynchronous:
        async with AsyncBot(TOKEN, transport=httpx.MockTransport(handler)) as abot:
            for coro in (abot.get_me, abot.get_webhook_info):
                with pytest.raises(errors.ZaloError) as info:
                    await coro()
                caught.append(info.value)
    else:
        with Bot(TOKEN, transport=httpx.MockTransport(handler)) as bot:
            for call in (bot.get_me, bot.get_webhook_info):
                with pytest.raises(errors.ZaloError) as info:
                    call()
                caught.append(info.value)
    assert isinstance(caught[0], errors.NetworkError)
    for exc in caught:
        assert exc.__context__ is None
        assert exc.__cause__ is None
        assert TOKEN not in _all_text(exc)


# --- cancelling start_polling (it used to leave the long poll running and lose its message) --------------------


async def test_regression_cancelled_polling_cancels_its_long_poll() -> None:
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("getWebhookInfo"):
            return httpx.Response(200, json={"ok": True, "result": {"url": ""}})
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        raise AssertionError("not cancelled")

    async with AsyncBot(TOKEN, transport=httpx.MockTransport(handler)) as bot:
        task = asyncio.create_task(Dispatcher().start_polling(bot))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(cancelled.wait(), 2)
    leftover = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    assert leftover == []


# --- retries must not send a message twice ---------------------------------------------------------------------


def _counting(exc: Exception) -> tuple[httpx.MockTransport, list[str]]:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path.rsplit("/", 1)[-1])
        if len(calls) == 1:
            raise exc
        return httpx.Response(200, json={"ok": True, "result": {"message_id": "m", "date": 1}})

    return httpx.MockTransport(handler), calls


@pytest.mark.parametrize("exc", [httpx.ReadTimeout("slow"), httpx.RemoteProtocolError("reset")])
def test_regression_send_not_retried_after_the_request_may_have_arrived(
    exc: Exception, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("zalobot.client.time.sleep", lambda s: None)
    transport, calls = _counting(exc)
    with Bot(TOKEN, transport=transport, retry=RetryPolicy(attempts=3)) as bot:
        with pytest.raises(errors.NetworkError) as info:
            bot.send_message("c", "hello")
        assert info.value.request_sent is True
        assert bot.get_me().raw  # reads are still retried: the failed one above counted once
    assert calls == ["sendMessage", "getMe"]


@pytest.mark.parametrize("exc", [httpx.ConnectError("refused"), httpx.ConnectTimeout("slow"), httpx.PoolTimeout("x")])
def test_send_retried_when_the_request_never_left(exc: Exception, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("zalobot.client.time.sleep", lambda s: None)
    transport, calls = _counting(exc)
    with Bot(TOKEN, transport=transport, retry=RetryPolicy(attempts=3)) as bot:
        assert bot.send_message("c", "hello").message_id == "m"
    assert calls == ["sendMessage", "sendMessage"]


async def test_regression_async_send_not_retried_after_read_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr("zalobot.client.asyncio.sleep", no_sleep)
    transport, calls = _counting(httpx.ReadTimeout("slow"))
    async with AsyncBot(TOKEN, transport=transport, retry=RetryPolicy(attempts=3)) as bot:
        with pytest.raises(errors.NetworkError):
            await bot.send_message("c", "hello")
    assert calls == ["sendMessage"]


def test_read_timeout_on_a_read_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("zalobot.client.time.sleep", lambda s: None)
    transport, calls = _counting(httpx.ReadTimeout("slow"))
    with Bot(TOKEN, transport=transport, retry=RetryPolicy(attempts=3)) as bot:
        bot.get_webhook_info()
    assert calls == ["getWebhookInfo", "getWebhookInfo"]


# --- fallback only where it works ------------------------------------------------------------------------------


def test_regression_fallback_only_on_the_dispatcher() -> None:
    assert not hasattr(Router(), "fallback")
    assert callable(Dispatcher().fallback)


# --- a webhook set while polling ends the loop --------------------------------------------------------------------


def test_regression_webhook_set_during_polling_raises(fake: FakeZalo) -> None:
    dp = Dispatcher()

    @dp.message()
    def handler(ctx: Context) -> None:
        fake.webhook_url = "https://example.com/hook"  # someone registers a webhook meanwhile

    fake.push_text("x")
    with fake.bot() as bot, pytest.raises(WebhookActiveError):
        dp.run_polling(bot, backoff_start=0.001)


async def test_regression_webhook_set_during_async_polling_raises(fake: FakeZalo) -> None:
    dp = Dispatcher()

    @dp.message()
    async def handler(ctx: AsyncContext) -> None:
        fake.webhook_url = "https://example.com/hook"

    fake.push_text("x")
    async with fake.async_bot() as bot:
        with pytest.raises(WebhookActiveError):
            await asyncio.wait_for(dp.start_polling(bot, backoff_start=0.001), 3)


def test_bad_request_without_webhook_keeps_polling(fake: FakeZalo) -> None:
    dp = Dispatcher()
    dp.message()(lambda ctx: dp.stop())
    fake.fail(400, method="getUpdates")
    fake.push_text("x")
    with fake.bot() as bot:
        dp.run_polling(bot, backoff_start=0.001)
    assert [m for m, _ in fake.calls].count("getWebhookInfo") == 2


# --- the 2000 limit counted like Zalo's Java server (UTF-16 units) ------------------------------------------------


def test_regression_text_limit_counts_utf16_units(fake: FakeZalo) -> None:
    emoji = "😀" * 1001  # 1001 code points, 2002 UTF-16 units
    with fake.bot() as bot, pytest.raises(ValueError, match="2002"):
        bot.send_message("c", emoji)
    pieces = split_text(emoji)
    assert all(utf16_len(p) <= 2000 for p in pieces)
    assert "".join(pieces) == emoji
    assert all("\ud83d" not in p[-1:] for p in pieces)  # no surrogate pair cut in half


def test_split_text_utf16_on_line_breaks() -> None:
    text = ("😀" * 600 + "\n") * 3
    pieces = split_text(text.rstrip("\n"))
    assert all(utf16_len(p) <= 2000 for p in pieces)
    assert "\n".join(pieces) == text.rstrip("\n")


# --- stop() before or around a run ---------------------------------------------------------------------------------


def test_regression_stop_before_run_is_kept(fake: FakeZalo) -> None:
    dp = Dispatcher()
    dp.stop()
    fake.push_text("x")
    with fake.bot() as bot:
        dp.run_polling(bot)
    assert [m for m, _ in fake.calls] == ["getWebhookInfo"]
    # the stop is used up: a second run polls again
    dp.message()(lambda ctx: dp.stop())
    with fake.bot() as bot:
        dp.run_polling(bot)
    assert not fake.updates


async def test_regression_stop_before_async_run_is_kept(fake: FakeZalo) -> None:
    dp = Dispatcher()
    dp.stop()
    async with fake.async_bot() as bot:
        await asyncio.wait_for(dp.start_polling(bot), 2)
    assert [m for m, _ in fake.calls] == ["getWebhookInfo"]


def test_regression_stop_after_the_loop_closed_is_harmless(fake: FakeZalo) -> None:
    dp = Dispatcher()
    loop = asyncio.new_event_loop()
    loop.close()
    dp._loop, dp._async_stop = loop, asyncio.Event()
    dp.stop()  # used to raise RuntimeError: Event loop is closed


# --- a failed webhook re-check backs off instead of ending polling ------------------------------------------------


def test_regression_failed_webhook_recheck_keeps_polling(fake: FakeZalo) -> None:
    dp = Dispatcher()
    dp.message()(lambda ctx: dp.stop())
    fake.fail(400, method="getUpdates")
    fake.fail(429, method="getWebhookInfo")
    fake.push_text("x")
    with fake.bot() as bot:
        dp.run_polling(bot, backoff_start=0.001, check_webhook=False)
    assert not fake.updates


async def test_regression_failed_webhook_recheck_keeps_async_polling(fake: FakeZalo) -> None:
    dp = Dispatcher()

    @dp.message()
    async def handler(ctx: AsyncContext) -> None:
        dp.stop()

    fake.fail(400, method="getUpdates")
    fake.fail(500, method="getWebhookInfo")
    fake.push_text("x")
    async with fake.async_bot() as bot:
        await asyncio.wait_for(dp.start_polling(bot, backoff_start=0.001, check_webhook=False), 3)
    assert not fake.updates


def test_dead_token_during_webhook_recheck_stops(fake: FakeZalo) -> None:
    dp = Dispatcher()
    fake.fail(400, method="getUpdates")
    fake.fail(401, method="getWebhookInfo")
    with fake.bot() as bot, pytest.raises(errors.Unauthorized):
        dp.run_polling(bot, backoff_start=0.001, check_webhook=False)


# --- the real API differs from the docs (seen live, 8 Nov 2026) --------------------------------------------------
# With no webhook set: getWebhookInfo -> 404 "Not Found", deleteWebhook -> 400, testWebhook -> 400. Errors come
# with HTTP 200 and the code in the body. getMe also returns display_name.

REAL_NO_WEBHOOK = {"ok": False, "description": "Not Found", "error_code": 404}
REAL_GET_ME = {
    "ok": True,
    "result": {
        "id": "1234567890123456789",
        "account_name": "bot.AbCdEfGh",
        "account_type": "BASIC",
        "can_join_groups": True,
        "display_name": "Example bot",
    },
    "error_code": 0,
}


def _real(request: httpx.Request) -> httpx.Response:
    method = request.url.path.rsplit("/", 1)[-1]
    if method == "getWebhookInfo":
        return httpx.Response(200, json=REAL_NO_WEBHOOK)
    if method == "getMe":
        return httpx.Response(200, json=REAL_GET_ME)
    return httpx.Response(200, json={"ok": False, "description": "Request timeout", "error_code": 408})


def test_regression_no_webhook_404_means_none() -> None:
    with Bot(TOKEN, transport=httpx.MockTransport(_real)) as bot:
        info = bot.get_webhook_info()
    assert info.url == ""
    assert info.updated_at is None


async def test_regression_no_webhook_404_means_none_async() -> None:
    async with AsyncBot(TOKEN, transport=httpx.MockTransport(_real)) as bot:
        assert (await bot.get_webhook_info()).url == ""


def test_regression_polling_starts_on_a_bot_without_webhook() -> None:
    dp = Dispatcher()
    polls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("getUpdates"):
            polls.append(1)
            dp.stop()
        return _real(request)

    with Bot(TOKEN, transport=httpx.MockTransport(handler)) as bot:
        dp.run_polling(bot)
    assert polls == [1]


def test_regression_get_me_display_name() -> None:
    with Bot(TOKEN, transport=httpx.MockTransport(_real)) as bot:
        me = bot.get_me()
    assert me.display_name == "Example bot"
    assert me.can_join_groups is True


def test_regression_fake_matches_the_real_api_without_webhook(fake: FakeZalo) -> None:
    client = httpx.Client(transport=fake.transport)
    base = f"https://bot-api.zaloplatforms.com/bot{TOKEN}"
    answers = {m: client.post(f"{base}/{m}", json={}) for m in ("getWebhookInfo", "deleteWebhook", "testWebhook")}
    client.close()
    assert {m: (r.status_code, r.json()["error_code"]) for m, r in answers.items()} == {
        "getWebhookInfo": (200, 404),
        "deleteWebhook": (200, 400),
        "testWebhook": (200, 400),
    }
    with fake.bot() as bot:
        assert bot.get_webhook_info().url == ""
        with pytest.raises(errors.BadRequest):
            bot.delete_webhook()
        with pytest.raises(errors.BadRequest, match="setWebhook"):
            bot.test_webhook()


def test_fake_after_a_webhook_was_deleted(fake: FakeZalo) -> None:
    with fake.bot() as bot:
        bot.set_webhook("https://example.com/hook", "secret-123")
        bot.delete_webhook()
        assert bot.get_webhook_info().url == ""
        assert bot.get_webhook_info().updated_at is not None  # a real answer now, not the 404
        assert bot.delete_webhook().url == ""
        with pytest.raises(errors.BadRequest, match="setWebhook"):
            bot.test_webhook()
