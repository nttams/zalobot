from __future__ import annotations

import json

import pytest

from zalobot import AsyncContext, AsyncWebhookHandler, Context, Dispatcher, F, WebhookHandler
from zalobot.testing import FakeZalo
from zalobot.webhook import SECRET_HEADER, parse_update, verify_secret

SECRET = "webhook-secret-123"


def test_verify_secret() -> None:
    assert verify_secret({SECRET_HEADER: SECRET}, SECRET)
    assert verify_secret({"x-bot-api-secret-token": SECRET}, SECRET)
    assert verify_secret({"X-BOT-API-SECRET-TOKEN": SECRET}, SECRET)
    assert not verify_secret({SECRET_HEADER: "wrong"}, SECRET)
    assert not verify_secret({}, SECRET)
    assert not verify_secret({SECRET_HEADER: SECRET + "x"}, SECRET)
    with pytest.raises(ValueError):
        verify_secret({SECRET_HEADER: ""}, "")


def test_parse_update() -> None:
    body = {"event_name": "message.text.received", "message": {"message_id": "m1", "text": "hi"}}
    assert parse_update(json.dumps(body)).text == "hi"
    assert parse_update(json.dumps(body).encode()).text == "hi"
    assert parse_update(body).text == "hi"
    for bad in [b"not json", b"[1]", b"", "null"]:
        with pytest.raises(ValueError):
            parse_update(bad)


def test_webhook_handler_end_to_end(fake: FakeZalo) -> None:
    dp = Dispatcher()

    @dp.message(F.text)
    def echo(ctx: Context) -> None:
        ctx.reply_text(f"echo: {ctx.text}")

    @dp.message(F.photo)
    def broken(ctx: Context) -> None:
        raise RuntimeError("bug")

    with fake.bot() as bot:
        bot.set_webhook("https://example.com/hook", SECRET)
        handler = WebhookHandler(dp, bot, SECRET)
        fake.push_text("xin chào")
        fake.push_photo()
        assert [s for s, _ in fake.deliver_webhook(handler)] == [200, 200]
        fake.push_text("intruder")
        assert fake.deliver_webhook(handler, secret="guess-1234") == [(403, b'{"message":"Unauthorized"}')]
        assert handler.handle({SECRET_HEADER: SECRET}, b"{oops") == (400, b'{"message":"Bad request"}')
    assert [r.text for r in fake.sent] == ["echo: xin chào"]


async def test_async_webhook_handler(fake: FakeZalo) -> None:
    dp = Dispatcher()

    @dp.message(F.text)
    async def echo(ctx: AsyncContext) -> None:
        await ctx.reply_text(f"echo: {ctx.text}")

    async with fake.async_bot() as bot:
        await bot.set_webhook("https://example.com/hook", SECRET)
        handler = AsyncWebhookHandler(dp, bot, SECRET)
        fake.push_text("một")
        fake.push_text("hai")
        assert [s for s, _ in await fake.adeliver_webhook(handler)] == [200, 200]
        fake.push_text("x")
        assert [s for s, _ in await fake.adeliver_webhook(handler, secret="nope-nope")] == [403]
        assert (await handler.handle({SECRET_HEADER: SECRET}, "[]"))[0] == 400
    assert [r.text for r in fake.sent] == ["echo: một", "echo: hai"]


def test_redelivered_update_is_handled_once(fake: FakeZalo) -> None:
    dp = Dispatcher()
    dp.message()(lambda ctx: ctx.reply_text("ok"))
    with fake.bot() as bot:
        handler = WebhookHandler(dp, bot, SECRET)
        event = fake.push_text("x")
        fake.updates.append(event)
        fake.webhook_secret = SECRET
        fake.deliver_webhook(handler)
    assert len(fake.sent) == 1


@pytest.mark.parametrize("secret", ["", "short", "x" * 257])
def test_handler_needs_a_valid_secret(fake: FakeZalo, secret: str) -> None:
    with pytest.raises(ValueError):
        WebhookHandler(Dispatcher(), fake.bot(), secret)
    with pytest.raises(ValueError):
        AsyncWebhookHandler(Dispatcher(), fake.async_bot(), secret)
