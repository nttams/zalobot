from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

import zalobot
from zalobot import AsyncBot, Bot, ChatAction, RetryPolicy, Text, errors
from zalobot.testing import FakeZalo

from .conftest import TOKEN, answering, raising, recording

DOCS_UPDATE = {
    "event_name": "message.text.received",
    "message": {
        "message_id": "2d758cb5e222177a4e35",
        "date": 1750316131602,
        "message_type": "CHAT_TEXT",
        "from": {"id": "6ede9afa66b88fe6d6a9", "display_name": "Ted", "is_bot": False},
        "chat": {"id": "6ede9afa66b88fe6d6a9", "chat_type": "PRIVATE"},
        "text": "Xin chào",
    },
}


# --- all 11 methods, sync ------------------------------------------------------------------------------------


def test_get_me(fake: FakeZalo) -> None:
    with fake.bot() as bot:
        me = bot.get_me()
    assert me.id == "1459232241454765289"
    assert me.account_name == "bot.FakeZalo"
    assert me.can_join_groups is False
    assert me.raw["account_type"] == "BASIC"


def test_get_updates_parses_docs_sample() -> None:
    with Bot(TOKEN, transport=answering({"ok": True, "result": DOCS_UPDATE})) as bot:
        [update] = bot.get_updates()
    assert update.is_text
    m = update.message
    assert m is not None
    assert m.text == "Xin chào"
    assert m.from_user.display_name == "Ted"
    assert m.chat.is_private and not m.chat.is_group
    assert m.date == datetime(2025, 6, 19, 6, 55, 31, 602000, tzinfo=UTC)
    assert update.raw == DOCS_UPDATE


@pytest.mark.parametrize(
    ("result", "count"),
    [(DOCS_UPDATE, 1), ([DOCS_UPDATE, DOCS_UPDATE], 2), (None, 0), ([], 0), ({}, 0), (["junk", DOCS_UPDATE], 1)],
)
def test_get_updates_result_shapes(result: Any, count: int) -> None:
    with Bot(TOKEN, transport=answering({"ok": True, "result": result})) as bot:
        assert len(bot.get_updates()) == count


def test_get_updates_408_is_no_message(fake: FakeZalo) -> None:
    with fake.bot() as bot:
        first, second = bot.get_updates(), bot.get_updates()
    assert first == [] and second == []
    first.append("x")  # type: ignore[arg-type]
    assert second == []  # each idle poll gets its own list


def test_get_updates_sends_timeout_as_string() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    with Bot(TOKEN, transport=recording(calls, {"ok": True, "result": None})) as bot:
        bot.get_updates(timeout=5)
    assert calls == [(f"/bot{TOKEN}/getUpdates", {"timeout": "5"})]


def test_get_updates_rejects_bad_timeout(fake: FakeZalo) -> None:
    with fake.bot() as bot, pytest.raises(ValueError, match="timeout"):
        bot.get_updates(timeout=-1)


def test_webhook_methods(fake: FakeZalo) -> None:
    with fake.bot() as bot:
        info = bot.set_webhook("https://example.com/hook", "s3cret-token")
        assert info.url == "https://example.com/hook"
        assert info.verification is not None and info.verification.ok
        assert info.verification.outcome == "webhook.ok"
        assert bot.get_webhook_info().url == "https://example.com/hook"
        fake.webhook_outcome, fake.webhook_hint = "webhook.http.403", "Check WAF rules"
        check = bot.test_webhook()
        assert not check.ok and check.outcome == "webhook.http.403" and check.hint == "Check WAF rules"
        with pytest.raises(errors.BadRequest, match="deleteWebhook"):
            bot.get_updates()
        deleted = bot.delete_webhook()
        assert deleted.url == "" and deleted.updated_at is not None
        assert bot.get_webhook_info().url == ""
        assert bot.get_updates() == []


def test_send_methods(fake: FakeZalo) -> None:
    with fake.bot() as bot:
        sent = bot.send_message("chat1", "hello")
        assert sent.message_id and sent.date is not None
        bot.send_photo("chat1", "https://example.com/a.jpg", caption="ảnh")
        bot.send_sticker("chat1", "bfe458bf64fa8da4d4eb")
        bot.send_voice("chat1", "https://example.com/v.aac")
        assert bot.send_chat_action("chat1") is True
    assert [(r.method, r.chat_id) for r in fake.sent] == [
        ("sendMessage", "chat1"),
        ("sendPhoto", "chat1"),
        ("sendSticker", "chat1"),
        ("sendVoice", "chat1"),
        ("sendChatAction", "chat1"),
    ]
    assert fake.sent[1].fields["caption"] == "ảnh"
    assert fake.sent[4].fields["action"] == "typing"
    assert fake.sent[0].message_id == sent.message_id


def test_send_message_parse_mode_and_text(fake: FakeZalo) -> None:
    with fake.bot() as bot:
        bot.send_message("c", "**hi**", parse_mode="markdown")
        bot.send_message("c", Text().bold("hi"))
        with pytest.raises(ValueError, match="not both"):
            bot.send_message("c", Text().bold("hi"), parse_mode="html")
        with pytest.raises(ValueError, match="markdownv2"):
            bot.send_message("c", "x", parse_mode="markdownv2")
    assert fake.sent[0].fields == {"chat_id": "c", "text": "**hi**", "parse_mode": "markdown"}
    assert fake.sent[1].fields == {"chat_id": "c", "text": "hi", "text_styles": [{"start": 0, "len": 2, "st": ["b"]}]}


def test_chat_action_values(fake: FakeZalo) -> None:
    with fake.bot() as bot:
        bot.send_chat_action("c", ChatAction.UPLOAD_PHOTO)
        with pytest.raises(ValueError):
            bot.send_chat_action("c", "dancing")
    assert fake.sent[0].fields["action"] == "upload_photo"


def test_send_long_message(fake: FakeZalo) -> None:
    text = "\n".join(f"line {i:04d} " + "x" * 90 for i in range(60))  # ~6000 characters
    with fake.bot() as bot:
        sent = bot.send_long_message("c", text)
    assert len(sent) == len(fake.sent) >= 3
    assert all(len(r.text or "") <= 2000 for r in fake.sent)
    assert "\n".join(r.text or "" for r in fake.sent) == text


# --- validation before any HTTP call -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (lambda b: b.send_message("c", ""), "text is 0"),
        (lambda b: b.send_message("c", "x" * 2001), "text is 2001"),
        (lambda b: b.send_message("", "x"), "chat_id"),
        (lambda b: b.send_photo("c", "/tmp/a.jpg"), "URL"),
        (lambda b: b.send_photo("c", "https://e.com/a.jpg", caption=""), "caption"),
        (lambda b: b.send_photo("c", "https://e.com/a.jpg", caption="x" * 2001), "caption"),
        (lambda b: b.send_sticker("c", " "), "sticker"),
        (lambda b: b.send_voice("c", "https://e.com/a.mp3"), ".aac"),
        (lambda b: b.send_voice("c", "file.aac"), "URL"),
        (lambda b: b.set_webhook("http://e.com/h", "12345678"), "https"),
        (lambda b: b.set_webhook("https://e.com/h", "1234567"), "secret_token"),
        (lambda b: b.set_webhook("https://e.com/h", "x" * 257), "secret_token"),
    ],
)
def test_validation(call: Any, match: str) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    with (
        Bot(TOKEN, transport=recording(calls, {"ok": True, "result": {}})) as bot,
        pytest.raises(ValueError, match=match),
    ):
        call(bot)
    assert calls == []


def test_voice_url_with_query_string(fake: FakeZalo) -> None:
    with fake.bot() as bot:
        bot.send_voice("c", "https://cdn.example.com/v.aac?sig=abc")
    assert fake.sent[0].method == "sendVoice"


@pytest.mark.parametrize("token", ["", "   ", "has space", "a/b"])
def test_bad_token(token: str) -> None:
    with pytest.raises(ValueError):
        Bot(token)


# --- errors --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "cls"),
    [
        (400, errors.BadRequest),
        (401, errors.Unauthorized),
        (403, errors.Forbidden),
        (404, errors.NotFound),
        (408, errors.TimedOut),
        (410, errors.InvalidChat),
        (429, errors.QuotaExceeded),
        (500, errors.ZaloError),
    ],
)
def test_error_codes(fake: FakeZalo, code: int, cls: type[errors.ZaloError]) -> None:
    fake.fail(code, "boom")
    with fake.bot() as bot, pytest.raises(cls) as info:
        bot.get_me()
    assert type(info.value) is cls
    assert info.value.code == code and info.value.description == "boom" and info.value.method == "getMe"
    assert str(info.value) == f"getMe: {code} boom"


def test_error_in_http_200_body() -> None:
    answer = {"ok": False, "error_code": 429, "description": "Quota exceeded"}
    with Bot(TOKEN, transport=answering(answer, 200)) as bot, pytest.raises(errors.QuotaExceeded):
        bot.get_me()


def test_error_code_taken_from_http_status_when_missing() -> None:
    with Bot(TOKEN, transport=answering({"ok": False}, 401)) as bot, pytest.raises(errors.Unauthorized):
        bot.get_me()


@pytest.mark.parametrize("body", [b"<html>502 Bad Gateway</html>", b"", b"[1, 2]"])
def test_non_json_answer(body: bytes) -> None:
    with Bot(TOKEN, transport=answering(body, 502)) as bot, pytest.raises(errors.ZaloError) as info:
        bot.get_me()
    assert info.value.code == 502


def test_network_error() -> None:
    with (
        Bot(TOKEN, transport=raising(httpx.ConnectError("connection refused"))) as bot,
        pytest.raises(errors.NetworkError) as info,
    ):
        bot.get_me()
    assert info.value.code is None and "ConnectError" in str(info.value)
    assert info.value.__cause__ is None
    assert info.value.__context__ is None


def test_wrong_token_is_unauthorized(fake: FakeZalo) -> None:
    with Bot("999:other", transport=fake.transport) as bot, pytest.raises(errors.Unauthorized):
        bot.get_me()


def test_unknown_method_is_not_found(fake: FakeZalo) -> None:
    from zalobot._core import Call

    with fake.bot() as bot, pytest.raises(errors.NotFound):
        bot.call(Call("sendInvoice", {}, lambda r: r))


# --- the token never leaks -----------------------------------------------------------------------------------


def _leaky_transport(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/getMe"):
        return httpx.Response(401, json={"ok": False, "error_code": 401, "description": f"bad token {TOKEN}"})
    if path.endswith("/getWebhookInfo"):
        return httpx.Response(502, content=f"proxy error for {request.url}".encode())
    raise httpx.ConnectError(f"cannot reach {request.url}")


def test_token_never_in_errors_repr_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    bot = Bot(TOKEN, transport=httpx.MockTransport(_leaky_transport))
    messages = []
    for call in (bot.get_me, bot.get_webhook_info, bot.test_webhook):
        with pytest.raises(errors.ZaloError) as info:
            call()
        messages += [str(info.value), repr(info.value), info.value.description]
    messages.append(repr(bot))
    bot.close()
    assert messages and all(TOKEN not in m for m in messages)
    assert any("<token>" in m for m in messages)
    assert caplog.records, "httpx should have logged the requests"
    assert all(TOKEN not in r.getMessage() for r in caplog.records)


def test_httpx_request_log_is_redacted(fake: FakeZalo, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="httpx")
    with fake.bot() as bot:
        bot.get_me()
    lines = [r.getMessage() for r in caplog.records if r.name == "httpx"]
    assert lines and all(TOKEN not in line and "<token>" in line for line in lines)


def test_token_property_and_repr(fake: FakeZalo) -> None:
    with fake.bot() as bot:
        assert bot.token == TOKEN
        assert TOKEN not in repr(bot)


# --- retries -------------------------------------------------------------------------------------------------


def test_retry_on_quota_then_success(fake: FakeZalo, monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("zalobot.client.time.sleep", sleeps.append)
    fake.fail(429, times=2)
    with fake.bot(retry=RetryPolicy(attempts=3, base_delay=0.5)) as bot:
        assert bot.get_me().id
    assert sleeps == [0.5, 1.0]


def test_retry_gives_up(fake: FakeZalo, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("zalobot.client.time.sleep", lambda s: None)
    fake.fail(429, times=5)
    with fake.bot(retry=RetryPolicy(attempts=3)) as bot, pytest.raises(errors.QuotaExceeded):
        bot.get_me()
    assert len(fake.calls) == 3


def test_never_retries_401(fake: FakeZalo, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("zalobot.client.time.sleep", lambda s: pytest.fail("slept"))
    fake.fail(401, times=5)
    with fake.bot(retry=RetryPolicy(attempts=5)) as bot, pytest.raises(errors.Unauthorized):
        bot.get_me()
    assert len(fake.calls) == 1


def test_no_retry_by_default(fake: FakeZalo) -> None:
    fake.fail(429)
    with fake.bot() as bot, pytest.raises(errors.QuotaExceeded):
        bot.get_me()
    assert len(fake.calls) == 1


def test_retry_network_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("zalobot.client.time.sleep", lambda s: None)
    tries = []

    def flaky(request: httpx.Request) -> httpx.Response:
        tries.append(1)
        if len(tries) < 3:
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200, json={"ok": True, "result": {"id": "1"}})

    with Bot(TOKEN, transport=httpx.MockTransport(flaky), retry=RetryPolicy(attempts=3)) as bot:
        assert bot.get_me().id == "1"
    with (
        Bot(TOKEN, transport=raising(httpx.ReadTimeout("slow")), retry=RetryPolicy(retry_network=False)) as bot,
        pytest.raises(errors.NetworkError),
    ):
        bot.get_me()


def test_retry_policy_delays() -> None:
    policy = RetryPolicy(attempts=10, base_delay=1, max_delay=5)
    assert [policy.delay(n) for n in range(1, 6)] == [1, 2, 4, 5, 5]
    with pytest.raises(ValueError):
        RetryPolicy(attempts=0)


def test_external_client_is_not_closed(fake: FakeZalo) -> None:
    client = httpx.Client(transport=fake.transport)
    with Bot(TOKEN, client=client) as bot:
        bot.get_me()
    assert not client.is_closed
    client.close()


# --- async ---------------------------------------------------------------------------------------------------


async def test_async_all_methods(fake: FakeZalo) -> None:
    fake.push_text("hi")
    async with fake.async_bot() as bot:
        assert (await bot.get_me()).account_name == "bot.FakeZalo"
        [update] = await bot.get_updates()
        assert update.text == "hi"
        assert await bot.get_updates() == []
        await bot.send_message("c", "hello")
        await bot.send_photo("c", "https://e.com/a.jpg")
        await bot.send_sticker("c", "abc")
        await bot.send_voice("c", "https://e.com/v.aac")
        assert await bot.send_chat_action("c") is True
        assert len(await bot.send_long_message("c", "a\n" * 1500)) == 2
        info = await bot.set_webhook("https://e.com/h", "secret-123")
        assert info.verification is not None
        assert (await bot.test_webhook()).ok
        assert (await bot.get_webhook_info()).url == "https://e.com/h"
        assert (await bot.delete_webhook()).url == ""
    assert [r.method for r in fake.sent][:5] == [
        "sendMessage",
        "sendPhoto",
        "sendSticker",
        "sendVoice",
        "sendChatAction",
    ]


async def test_async_errors_and_retry(fake: FakeZalo, monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr("zalobot.client.asyncio.sleep", no_sleep)
    fake.fail(429, times=1)
    async with fake.async_bot(retry=RetryPolicy(attempts=2)) as bot:
        assert (await bot.get_me()).id
        fake.fail(401)
        with pytest.raises(errors.Unauthorized):
            await bot.get_me()
        fake.fail(408)
        with pytest.raises(errors.TimedOut):
            await bot.get_me()


async def test_async_network_error_redacted() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    async with AsyncBot(TOKEN, transport=httpx.MockTransport(boom)) as bot:
        with pytest.raises(errors.NetworkError) as info:
            await bot.get_me()
    assert TOKEN not in str(info.value) and "<token>" in str(info.value)


def test_public_api_exports() -> None:
    for name in zalobot.__all__:
        assert hasattr(zalobot, name), name
