"""The examples and the README quickstart run against FakeZalo."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

import zalobot
from zalobot import Dispatcher, Text
from zalobot.testing import SECRET_HEADER, FakeZalo

ROOT = Path(__file__).resolve().parent.parent
SECRET = "example-secret-1"


def test_echo_polling(fake: FakeZalo) -> None:
    from examples import echo_polling

    fake.push_text("/start")
    fake.push_text("hello")
    fake.push_photo(caption="menu")
    with fake.bot() as bot:
        while fake.updates:
            for update in bot.get_updates():
                echo_polling.dp.feed(bot, update)
    assert [r.text for r in fake.sent] == [
        "Xin chào Ted! Send me anything and I'll send it back.",
        "hello",
        "Nice picture! Caption: menu",
    ]


async def test_echo_async(fake: FakeZalo) -> None:
    from examples import echo_async

    fake.push_text("hi")
    fake.push_text("in a group", chat_type="GROUP")
    async with fake.async_bot() as bot:
        while fake.updates:
            for update in await bot.get_updates():
                await echo_async.dp.feed_async(bot, update)
    assert [(r.method, r.text) for r in fake.sent] == [("sendChatAction", None), ("sendMessage", "hi")]


def test_rich_text(fake: FakeZalo) -> None:
    from examples.rich_text import order_summary

    summary = order_summary("1024", [("Cà phê sữa đá", 29000), ("Bánh mì", 25000)], paid=True)
    assert isinstance(summary, Text)
    assert summary.text == "Đơn hàng #1024\nCà phê sữa đá: 29,000đ\nBánh mì: 25,000đ\nTổng: 54,000đ ✅ đã thanh toán"
    with fake.bot() as bot:
        bot.send_message("chat", summary)
    styles = fake.sent[0].fields["text_styles"]
    assert [s["st"] for s in styles] == [["f_18"], ["lst_1"], ["lst_1"], ["b"], ["c_15a85f"]]
    assert "chưa" in order_summary("1", [("x", 1)], paid=False).text


def _post_all(fake: FakeZalo, post: Any, secret: str | None = None) -> list[int]:
    statuses = []
    for headers, body in fake._deliveries(secret):
        statuses.append(post(headers, body))
    return statuses


def test_webhook_flask(fake: FakeZalo) -> None:
    from examples.webhook_flask import create_app

    with fake.bot() as bot:
        client = create_app(bot, SECRET).test_client()
        fake.webhook_secret = SECRET
        fake.push_text("xin chào")

        def post(headers: dict[str, str], body: bytes) -> int:
            return client.post("/zalo/webhook", data=body, headers=headers).status_code

        assert _post_all(fake, post) == [200]
        fake.push_text("intruder")
        assert _post_all(fake, post, secret="wrong-secret") == [403]
        assert client.post("/zalo/webhook", data=b"junk", headers={SECRET_HEADER: SECRET}).status_code == 400
    assert [r.text for r in fake.sent] == ["You said: xin chào"]


def test_webhook_fastapi(fake: FakeZalo) -> None:
    from fastapi.testclient import TestClient

    from examples.webhook_fastapi import create_app

    bot = fake.async_bot()
    with TestClient(create_app(bot, SECRET)) as client:
        fake.webhook_secret = SECRET
        fake.push_text("một")

        def post(headers: dict[str, str], body: bytes) -> int:
            return client.post("/zalo/webhook", content=body, headers=headers).status_code

        assert _post_all(fake, post) == [200]
        fake.push_text("x")
        assert _post_all(fake, post, secret="wrong-secret") == [403]
    assert [r.text for r in fake.sent] == ["You said: một"]


def test_readme_quickstart(fake: FakeZalo, monkeypatch: pytest.MonkeyPatch) -> None:
    """The first python block in the README is a working echo bot of at most 10 lines."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    block = re.search(r"```python\n(.*?)```", readme, re.S)
    assert block, "README needs a python quickstart"
    code = block.group(1)
    assert len([line for line in code.splitlines() if line.strip()]) <= 10

    def run_once(self: Dispatcher, bot: Any, **kwargs: Any) -> None:
        with fake.bot() as fake_bot:
            for update in fake_bot.get_updates():
                self.feed(fake_bot, update)

    monkeypatch.setattr(zalobot.Dispatcher, "run_polling", run_once)
    monkeypatch.setenv("ZALO_BOT_TOKEN", "1234567890:fake-zalobot-token")
    fake.push_text("xin chào")
    exec(compile(code, "README.md", "exec"), {"__name__": "readme"})  # noqa: S102
    assert [r.text for r in fake.sent] == ["xin chào"]
