from __future__ import annotations

import json
from collections.abc import Mapping

import httpx
import pytest

from zalobot import QuotaExceeded
from zalobot.testing import SECRET_HEADER, FakeZalo

from .conftest import TOKEN


def test_push_shapes_match_docs(fake: FakeZalo) -> None:
    text = fake.push_text("Xin chào", chat_id="g1", user_id="u1", chat_type="GROUP")
    photo = fake.push_photo(caption="Ảnh sản phẩm")
    sticker = fake.push_sticker()
    voice = fake.push_voice()
    unsupported = fake.push_unsupported()
    assert text["event_name"] == "message.text.received"
    assert text["message"]["chat"] == {"id": "g1", "chat_type": "GROUP"}
    assert text["message"]["from"] == {"id": "u1", "display_name": "Ted", "is_bot": False}
    assert len(text["message"]["message_id"]) == 20 and isinstance(text["message"]["date"], int)
    assert photo["message"]["message_type"] == "CHAT_PHOTO" and photo["message"]["caption"] == "Ảnh sản phẩm"
    assert sticker["message"]["sticker"] and sticker["message"]["url"]
    assert voice["message"]["voice_url"].endswith(".aac")
    assert unsupported["event_name"] == "message.unsupported.received"
    assert "message_type" not in unsupported["message"]
    assert "caption" not in fake.push_photo()["message"]


def test_updates_come_one_per_call_in_order(fake: FakeZalo) -> None:
    fake.push_text("1")
    fake.push_text("2")
    with fake.bot() as bot:
        assert [u.text for u in bot.get_updates()] == ["1"]
        assert [u.text for u in bot.get_updates()] == ["2"]
        assert bot.get_updates() == []


def test_failures_by_method_and_count(fake: FakeZalo) -> None:
    fake.fail(429, method="sendMessage", times=2)
    with fake.bot() as bot:
        assert bot.get_me().id
        for _ in range(2):
            with pytest.raises(QuotaExceeded):
                bot.send_message("c", "x")
        bot.send_message("c", "x")
    assert len(fake.sent) == 1
    assert [m for m, _ in fake.calls] == ["getMe", "sendMessage", "sendMessage", "sendMessage"]


def test_fake_rejects_what_the_api_rejects(fake: FakeZalo) -> None:
    client = httpx.Client(transport=fake.transport)
    base = f"https://bot-api.zaloplatforms.com/bot{TOKEN}"
    cases = [
        (client.get(f"{base}/getMe"), 404),
        (client.post(f"{base}/nope", json={}), 404),
        (client.post(f"{base}/getMe", content=b"{bad json"), 400),
        (client.post(f"{base}/sendMessage", json={"text": "x"}), 400),
        (client.post(f"{base}/sendMessage", json={"chat_id": "c", "text": ""}), 400),
        (client.post(f"{base}/sendPhoto", json={"chat_id": "c"}), 400),
        (client.post(f"{base}/sendSticker", json={"chat_id": "c"}), 400),
        (client.post(f"{base}/sendVoice", json={"chat_id": "c", "voice_url": "x.mp3"}), 400),
        (client.post(f"{base}/sendChatAction", json={"chat_id": "c", "action": "dance"}), 400),
        (client.post(f"{base}/setWebhook", json={"url": "http://x", "secret_token": "12345678"}), 400),
    ]
    client.close()
    for response, code in cases:
        assert response.status_code == 200  # like the real API: the code is in the body
        body = response.json()
        assert body["ok"] is False
        assert body["error_code"] == code
        assert body["description"]
    assert fake.sent == []


class _Recorder:
    def __init__(self) -> None:
        self.seen: list[tuple[Mapping[str, str], bytes]] = []

    def handle(self, headers: Mapping[str, str], body: bytes) -> tuple[int, bytes]:
        self.seen.append((headers, body))
        return 200, b"{}"


class _AsyncRecorder(_Recorder):
    async def handle(self, headers: Mapping[str, str], body: bytes) -> tuple[int, bytes]:  # type: ignore[override]
        return super().handle(headers, body)


def test_deliver_webhook(fake: FakeZalo) -> None:
    with fake.bot() as bot:
        bot.set_webhook("https://example.com/hook", "my-secret-1")
    fake.push_text("a")
    fake.push_text("b")
    recorder = _Recorder()
    assert fake.deliver_webhook(recorder) == [(200, b"{}"), (200, b"{}")]
    assert [json.loads(b)["message"]["text"] for _, b in recorder.seen] == ["a", "b"]
    assert all(h[SECRET_HEADER] == "my-secret-1" for h, _ in recorder.seen)
    fake.push_text("c")
    fake.deliver_webhook(recorder, secret="wrong")
    assert recorder.seen[-1][0][SECRET_HEADER] == "wrong"
    assert not fake.updates


async def test_adeliver_webhook(fake: FakeZalo) -> None:
    fake.webhook_secret = "s" * 8
    fake.push_text("a")
    recorder = _AsyncRecorder()
    assert await fake.adeliver_webhook(recorder) == [(200, b"{}")]
    assert recorder.seen[0][0][SECRET_HEADER] == "s" * 8
