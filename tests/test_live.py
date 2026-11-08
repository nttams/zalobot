"""Live tests against the real Zalo Bot API. Skipped unless ZALOBOT_TEST_TOKEN is set.

Use a bot made only for testing: these tests set and delete a webhook, which turns long polling off for the bot
while it runs. Before running, send the test bot a text message and a sticker from your Zalo account; the tests
reply only into that chat.

    ZALOBOT_TEST_TOKEN=... uv run pytest -m live -v

Optional: ZALOBOT_TEST_WAIT (seconds to wait for your message), ZALOBOT_TEST_CHAT_ID (else taken from the first
message), ZALOBOT_TEST_PHOTO_URL,
ZALOBOT_TEST_VOICE_URL (a public .aac file), ZALOBOT_TEST_WEBHOOK=0 (skip the webhook test: while it runs, new
messages go to a dead webhook and are lost).
"""

from __future__ import annotations

import contextlib
import os
import secrets
import time
from collections.abc import Iterator

import pytest

from zalobot import Bot, ChatAction, Color, Text, Update, _core, errors

pytestmark = pytest.mark.live

TOKEN = os.environ.get("ZALOBOT_TEST_TOKEN", "")
PHOTO_URL = os.environ.get("ZALOBOT_TEST_PHOTO_URL", "https://www.python.org/static/img/python-logo.png")
VOICE_URL = os.environ.get("ZALOBOT_TEST_VOICE_URL", "https://filesamples.com/samples/audio/aac/sample1.aac")
# A public URL that does not run a webhook: Zalo's check of it must fail with a webhook.* outcome.
DEAD_WEBHOOK = "https://example.com/zalobot-live-test"

if not TOKEN:
    pytest.skip("set ZALOBOT_TEST_TOKEN to run the live tests", allow_module_level=True)


@pytest.fixture(scope="module")
def bot() -> Iterator[Bot]:
    with Bot(TOKEN) as b:
        if b.get_webhook_info().url:  # start from polling mode (deleteWebhook answers 400 when none is set)
            b.delete_webhook()
        yield b
        if b.get_webhook_info().url:  # leave it in polling mode
            b.delete_webhook()


@pytest.fixture(scope="module")
def received(bot: Bot) -> list[Update]:
    """Everything waiting for the bot. With ZALOBOT_TEST_WAIT=<seconds>, keep polling until a private message
    arrives (then a little longer, for a sticker sent right after it)."""
    deadline = time.monotonic() + float(os.environ.get("ZALOBOT_TEST_WAIT", "0"))
    updates: list[Update] = []
    while True:
        batch = bot.get_updates(timeout=3)
        updates += batch
        private = any(u.message and u.message.chat.is_private for u in updates)
        if not batch and (private or time.monotonic() >= deadline):
            break
    if private:  # a sticker sent right after the text
        for _ in range(3):
            updates += bot.get_updates(timeout=5)
    for u in updates:
        if u.message and u.message.chat.is_private:
            print(f"\ntest chat id: {u.message.chat.id} (set ZALOBOT_TEST_CHAT_ID to reuse it)")
            break
    return updates


@pytest.fixture(scope="module")
def chat_id(received: list[Update]) -> str:
    if os.environ.get("ZALOBOT_TEST_CHAT_ID"):
        return os.environ["ZALOBOT_TEST_CHAT_ID"]
    for u in received:
        if u.message and u.message.chat.is_private:
            return u.message.chat.id
    pytest.skip("send the test bot a message from your Zalo account first (or set ZALOBOT_TEST_CHAT_ID)")


def test_get_me(bot: Bot) -> None:
    me = bot.get_me()
    assert me.id
    assert me.account_name
    assert me.raw.get("account_type") is not None


def test_received_updates_parse(received: list[Update]) -> None:
    for u in received:
        assert u.event_name.startswith("message.")
        assert u.message is not None
        assert u.message.message_id
        assert u.message.date is not None
        assert u.message.from_user.id


def test_send_chat_action(bot: Bot, chat_id: str) -> None:
    assert bot.send_chat_action(chat_id, ChatAction.TYPING) is True


def test_send_message_plain_markdown_and_styles(bot: Bot, chat_id: str) -> None:
    plain = bot.send_message(chat_id, "zalobot live test: plain text ✓")
    assert plain.message_id
    assert plain.date is not None
    marked = bot.send_message(chat_id, "zalobot: **bold** _italic_ {red}red{/red}", parse_mode="markdown")
    assert marked.message_id
    styled = Text().bold("Đơn hàng #1024").plain(" 🎉 ").color(Color.GREEN, "đã giao ✅")
    assert bot.send_message(chat_id, styled).message_id


def test_send_long_message(bot: Bot, chat_id: str) -> None:
    text = "\n".join(f"zalobot long message line {i:03d} " + "·" * 60 for i in range(40))
    sent = bot.send_long_message(chat_id, text)
    assert len(sent) == 2


def test_send_photo(bot: Bot, chat_id: str) -> None:
    assert bot.send_photo(chat_id, PHOTO_URL, caption="zalobot live test: photo").message_id


def test_send_sticker(bot: Bot, chat_id: str, received: list[Update]) -> None:
    stickers = [u.message.sticker for u in received if u.message and u.message.sticker]
    if not stickers:
        pytest.skip("send the test bot a sticker first; its id is reused here")
    assert bot.send_sticker(chat_id, stickers[0]).message_id


def test_send_voice(bot: Bot, chat_id: str) -> None:
    assert bot.send_voice(chat_id, VOICE_URL).message_id


def test_error_for_unknown_chat(bot: Bot) -> None:
    with pytest.raises(errors.InvalidChat):
        bot.send_message("0000000000000000000", "nobody is here")


def test_no_webhook_answers(bot: Bot) -> None:
    assert bot.get_webhook_info().url == ""  # the API answers 404 here; the library turns it into ""
    with pytest.raises(errors.BadRequest, match="setWebhook"):
        bot.test_webhook()
    with contextlib.suppress(errors.BadRequest):  # 400 if the bot never had a webhook, else ok with url ""
        assert bot.delete_webhook().url == ""
    with pytest.raises(errors.NotFound):
        bot.call(_core.Call("sendInvoice", {}, lambda r: r))


def test_get_me_display_name(bot: Bot) -> None:
    assert bot.get_me().display_name


def test_bad_token_is_unauthorized() -> None:
    with Bot("1:not-a-real-token") as wrong, pytest.raises(errors.Unauthorized):
        wrong.get_me()


def test_webhook_cycle(bot: Bot) -> None:
    """Runs last. While the webhook is set (a few seconds), Zalo POSTs new messages to DEAD_WEBHOOK instead of
    queuing them for getUpdates, so a message sent then is lost: don't message the bot during this test.
    ZALOBOT_TEST_WEBHOOK=0 skips it."""
    if os.environ.get("ZALOBOT_TEST_WEBHOOK", "1") == "0":
        pytest.skip("ZALOBOT_TEST_WEBHOOK=0")
    print("\nwebhook test: messages sent to the bot in the next ~10 s are lost (they go to example.com)")
    secret = secrets.token_urlsafe(24)
    info = bot.set_webhook(DEAD_WEBHOOK, secret)
    try:
        assert info.url == DEAD_WEBHOOK
        assert info.updated_at is not None
        assert info.verification is not None
        assert info.verification.outcome.startswith("webhook.")
        assert not info.verification.ok
        assert bot.get_webhook_info().url == DEAD_WEBHOOK
        check = bot.test_webhook()
        assert not check.ok
        assert check.outcome.startswith("webhook.")
        assert check.hint
        with pytest.raises(errors.ZaloError):
            bot.get_updates(timeout=1)  # Zalo turns polling off while a webhook is set
    finally:
        deleted = bot.delete_webhook()
    assert deleted.url == ""
    assert bot.get_webhook_info().url == ""
    assert isinstance(bot.get_updates(timeout=1), list)
