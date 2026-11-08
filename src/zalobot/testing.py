"""An in-memory Zalo Bot API for tests: no network, no token, no Zalo account.

>>> fake = FakeZalo()
>>> fake.push_text("hi")                       # a user writes to the bot      # doctest: +ELLIPSIS
{...}
>>> with fake.bot() as bot:
...     [u] = bot.get_updates()
...     _ = bot.send_message(u.message.chat.id, "hello")
>>> fake.sent[0].text
'hello'

Answers follow the shapes on the official method pages (https://bot.zaloplatforms.com/docs/). Where the docs say
nothing, the fake picks one plausible behaviour and says so in the docstring.
"""

from __future__ import annotations

import json
import secrets
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from zalobot.client import AsyncBot, Bot
from zalobot.types import JSON, ChatType, EventName

__all__ = ["FakeZalo", "SentRecord"]

FAKE_TOKEN = "1234567890:fake-zalobot-token"  # noqa: S105 (a fake)
SECRET_HEADER = "X-Bot-Api-Secret-Token"  # noqa: S105 (a header name)

_SEND_METHODS = {"sendMessage", "sendPhoto", "sendSticker", "sendVoice", "sendChatAction"}
_METHODS = {
    "getMe",
    "getUpdates",
    "setWebhook",
    "testWebhook",
    "deleteWebhook",
    "getWebhookInfo",
} | _SEND_METHODS


class _SyncWebhook(Protocol):
    def handle(self, headers: Mapping[str, str], body: bytes) -> tuple[int, bytes]: ...


class _AsyncWebhook(Protocol):
    async def handle(self, headers: Mapping[str, str], body: bytes) -> tuple[int, bytes]: ...


@dataclass(frozen=True)
class SentRecord:
    """One send-type call the bot made (sendMessage, sendPhoto, sendSticker, sendVoice, sendChatAction)."""

    method: str
    chat_id: str
    fields: JSON
    message_id: str = ""

    @property
    def text(self) -> str | None:
        value = self.fields.get("text")
        return value if isinstance(value, str) else None


@dataclass
class _Failure:
    code: int
    description: str
    method: str | None
    times: int


def _now_ms() -> int:
    return int(time.time() * 1000)


def _message_id() -> str:
    return secrets.token_hex(10)


@dataclass
class FakeZalo:
    """A fake Zalo Bot Platform for one bot.

    - ``push_*`` queue incoming messages; ``getUpdates`` hands out one per call (as the docs show) and answers
      408 at once when the queue is empty (the real API waits ``timeout`` seconds first).
    - ``sent`` records every send call; ``calls`` records every call.
    - ``fail(code)`` makes the next call(s) fail with that Zalo error code.
    - While a webhook is set, ``getUpdates`` fails with 400: the docs say the two are exclusive but don't give the
      code, so the fake picks 400.
    - Where the real API differs from the docs, the fake does what the real API does (seen 8 Nov 2026): errors
      come with HTTP 200 and the code in the body; on a bot that never had a webhook, getWebhookInfo answers 404
      and deleteWebhook 400 (after one was set and deleted, both answer ok with url ""); testWebhook without a
      webhook answers 400; an unknown method is 404; getMe includes ``display_name``.
    """

    token: str = FAKE_TOKEN
    bot_id: str = "1459232241454765289"
    account_name: str = "bot.FakeZalo"
    account_type: str = "BASIC"
    can_join_groups: bool = False
    display_name: str = "Bot FakeZalo"
    webhook_outcome: str = "webhook.ok"
    webhook_hint: str = "Your endpoint responded successfully."
    updates: deque[JSON] = field(default_factory=deque)
    sent: list[SentRecord] = field(default_factory=list)
    calls: list[tuple[str, JSON]] = field(default_factory=list)
    webhook_url: str = ""
    webhook_secret: str = ""
    webhook_updated_at: int = 0
    webhook_ever_set: bool = False
    _failures: list[_Failure] = field(default_factory=list)

    # --- wiring ---------------------------------------------------------------------------------------------

    @property
    def transport(self) -> httpx.MockTransport:
        """An httpx transport for ``Bot(..., transport=)`` or ``AsyncBot(..., transport=)``."""
        return httpx.MockTransport(self._handle)

    def bot(self, **kwargs: Any) -> Bot:
        return Bot(self.token, transport=self.transport, **kwargs)

    def async_bot(self, **kwargs: Any) -> AsyncBot:
        return AsyncBot(self.token, transport=self.transport, **kwargs)

    # --- incoming messages ----------------------------------------------------------------------------------

    def push(
        self,
        event_name: str,
        chat_id: str,
        user_id: str,
        display_name: str,
        chat_type: str,
        message_type: str,
        **content: Any,
    ) -> JSON:
        event: JSON = {
            "event_name": event_name,
            "message": {
                "message_id": _message_id(),
                "date": _now_ms(),
                "message_type": message_type,
                "from": {"id": user_id, "display_name": display_name, "is_bot": False},
                "chat": {"id": chat_id, "chat_type": chat_type},
                **{k: v for k, v in content.items() if v is not None},
            },
        }
        if not message_type:
            del event["message"]["message_type"]
        self.updates.append(event)
        return event

    def push_text(
        self,
        text: str,
        *,
        chat_id: str = "6ede9afa66b88fe6d6a9",
        user_id: str | None = None,
        display_name: str = "Ted",
        chat_type: str = ChatType.PRIVATE,
    ) -> JSON:
        return self.push(EventName.TEXT, chat_id, user_id or chat_id, display_name, chat_type, "CHAT_TEXT", text=text)

    def push_photo(
        self,
        photo_url: str = "https://example.com/photo.jpg",
        caption: str | None = None,
        *,
        chat_id: str = "6ede9afa66b88fe6d6a9",
        user_id: str | None = None,
        display_name: str = "Ted",
        chat_type: str = ChatType.PRIVATE,
    ) -> JSON:
        return self.push(
            EventName.IMAGE,
            chat_id,
            user_id or chat_id,
            display_name,
            chat_type,
            "CHAT_PHOTO",
            photo_url=photo_url,
            caption=caption,
        )

    def push_sticker(
        self,
        sticker: str = "bfe458bf64fa8da4d4eb",
        url: str = "https://zalo-api.zadn.vn/api/emoticon/sticker/webpc?eid=46991",
        *,
        chat_id: str = "6ede9afa66b88fe6d6a9",
        user_id: str | None = None,
        display_name: str = "Ted",
        chat_type: str = ChatType.PRIVATE,
    ) -> JSON:
        return self.push(
            EventName.STICKER,
            chat_id,
            user_id or chat_id,
            display_name,
            chat_type,
            "CHAT_STICKER",
            sticker=sticker,
            url=url,
        )

    def push_voice(
        self,
        voice_url: str = "https://example.com/voice.aac",
        *,
        chat_id: str = "6ede9afa66b88fe6d6a9",
        user_id: str | None = None,
        display_name: str = "Ted",
        chat_type: str = ChatType.PRIVATE,
    ) -> JSON:
        return self.push(
            EventName.VOICE,
            chat_id,
            user_id or chat_id,
            display_name,
            chat_type,
            "CHAT_VOICE",
            voice_url=voice_url,
        )

    def push_unsupported(
        self,
        *,
        chat_id: str = "6ede9afa66b88fe6d6a9",
        user_id: str | None = None,
        display_name: str = "Ted",
        chat_type: str = ChatType.PRIVATE,
    ) -> JSON:
        """A message from a protected account: Zalo withholds the content."""
        return self.push(EventName.UNSUPPORTED, chat_id, user_id or chat_id, display_name, chat_type, "")

    # --- failures -------------------------------------------------------------------------------------------

    def fail(self, code: int, description: str | None = None, *, method: str | None = None, times: int = 1) -> None:
        """Make the next ``times`` calls (of ``method``, or any) fail with Zalo error ``code``."""
        names = {
            400: "Bad request",
            401: "Unauthorized",
            403: "Internal server error",
            404: "Not found",
            408: "Request timeout",
            429: "Quota exceeded",
        }
        self._failures.append(_Failure(code, description or names.get(code, "Error"), method, times))

    def _take_failure(self, method: str) -> _Failure | None:
        for f in self._failures:
            if f.method in (None, method):
                f.times -= 1
                if f.times <= 0:
                    self._failures.remove(f)
                return f
        return None

    # --- webhook delivery -----------------------------------------------------------------------------------

    def _deliveries(self, secret: str | None) -> list[tuple[dict[str, str], bytes]]:
        out = []
        while self.updates:
            headers = {
                "Content-Type": "application/json",
                SECRET_HEADER: self.webhook_secret if secret is None else secret,
            }
            out.append((headers, json.dumps(self.updates.popleft()).encode()))
        return out

    def deliver_webhook(self, handler: _SyncWebhook, *, secret: str | None = None) -> list[tuple[int, bytes]]:
        """POST every queued update to ``handler.handle`` as Zalo would (``secret`` overrides the header)."""
        return [handler.handle(h, b) for h, b in self._deliveries(secret)]

    async def adeliver_webhook(self, handler: _AsyncWebhook, *, secret: str | None = None) -> list[tuple[int, bytes]]:
        return [await handler.handle(h, b) for h, b in self._deliveries(secret)]

    # --- the API --------------------------------------------------------------------------------------------

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        prefix = f"/bot{self.token}/"
        if request.method != "POST":
            return _error(404, "Not found")
        if not path.startswith(prefix):
            return _error(401, "Unauthorized")
        method = path[len(prefix) :]
        if method not in _METHODS:
            return _error(404, "Not Found")
        try:
            fields = json.loads(request.content or b"{}")
        except ValueError:
            return _error(400, "Bad request")
        self.calls.append((method, fields))
        failure = self._take_failure(method)
        if failure:
            return _error(failure.code, failure.description)
        if method in _SEND_METHODS and not str(fields.get("chat_id") or ""):
            return _error(400, "chat_id is required")
        return getattr(self, f"_api_{method}")(fields)  # type: ignore[no-any-return]

    def _api_getMe(self, fields: JSON) -> httpx.Response:
        return _ok(
            {
                "id": self.bot_id,
                "account_name": self.account_name,
                "account_type": self.account_type,
                "can_join_groups": self.can_join_groups,
                "display_name": self.display_name,
            }
        )

    def _api_getUpdates(self, fields: JSON) -> httpx.Response:
        if self.webhook_url:
            return _error(400, "Webhook is active: call deleteWebhook before getUpdates")
        if not self.updates:
            return _error(408, "Request timeout")
        return _ok(self.updates.popleft())

    def _webhook_check(self) -> JSON:
        return {
            "ok": self.webhook_outcome == "webhook.ok",
            "url": self.webhook_url,
            "outcome": self.webhook_outcome,
            "hint": self.webhook_hint,
        }

    def _api_setWebhook(self, fields: JSON) -> httpx.Response:
        url, secret = str(fields.get("url") or ""), str(fields.get("secret_token") or "")
        if not url.startswith("https://") or not 8 <= len(secret) <= 256:
            return _error(400, "Bad request")
        self.webhook_url, self.webhook_secret, self.webhook_updated_at = url, secret, _now_ms()
        self.webhook_ever_set = True
        return _ok({"url": url, "updated_at": self.webhook_updated_at, "verification": self._webhook_check()})

    def _api_testWebhook(self, fields: JSON) -> httpx.Response:
        if not self.webhook_url:
            return _error(400, "No webhook url is configured for this bot. Call setWebhook first.")
        return _ok(self._webhook_check())

    def _api_deleteWebhook(self, fields: JSON) -> httpx.Response:
        if not (self.webhook_ever_set or self.webhook_url):
            return _error(400, "Bad request")
        self.webhook_url, self.webhook_secret, self.webhook_updated_at = "", "", _now_ms()
        return _ok({"url": "", "updated_at": self.webhook_updated_at})

    def _api_getWebhookInfo(self, fields: JSON) -> httpx.Response:
        if not (self.webhook_ever_set or self.webhook_url):
            return _error(404, "Not Found")
        return _ok({"url": self.webhook_url, "updated_at": self.webhook_updated_at})

    def _record(self, method: str, fields: JSON) -> httpx.Response:
        message_id = _message_id()
        self.sent.append(SentRecord(method, str(fields["chat_id"]), dict(fields), message_id))
        return _ok({"message_id": message_id, "date": _now_ms()})

    def _api_sendMessage(self, fields: JSON) -> httpx.Response:
        text = fields.get("text")
        if not isinstance(text, str) or not 1 <= len(text) <= 2000:
            return _error(400, "text must be 1 to 2000 characters")
        return self._record("sendMessage", fields)

    def _api_sendPhoto(self, fields: JSON) -> httpx.Response:
        if not fields.get("photo"):
            return _error(400, "photo is required")
        return self._record("sendPhoto", fields)

    def _api_sendSticker(self, fields: JSON) -> httpx.Response:
        if not fields.get("sticker"):
            return _error(400, "sticker is required")
        return self._record("sendSticker", fields)

    def _api_sendVoice(self, fields: JSON) -> httpx.Response:
        if not str(fields.get("voice_url") or "").split("?", 1)[0].lower().endswith(".aac"):
            return _error(400, "voice_url must be an .aac file")
        return self._record("sendVoice", fields)

    def _api_sendChatAction(self, fields: JSON) -> httpx.Response:
        if fields.get("action") not in ("typing", "upload_photo"):
            return _error(400, "Bad request")
        self.sent.append(SentRecord("sendChatAction", str(fields["chat_id"]), dict(fields)))
        return httpx.Response(200, json={"ok": True})


def _ok(result: Any) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


def _error(code: int, description: str) -> httpx.Response:
    """The real API answers errors with HTTP 200 and the code in the body."""
    return httpx.Response(200, json={"ok": False, "error_code": code, "description": description})
