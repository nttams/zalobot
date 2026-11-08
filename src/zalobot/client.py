"""``Bot`` (blocking) and ``AsyncBot`` (asyncio): one method per Zalo Bot API method.

Both share the request building and answer parsing in ``zalobot._core``; only the HTTP calls differ.
"""

from __future__ import annotations

import asyncio
import time
from types import TracebackType
from typing import Any, TypeVar

import httpx

from zalobot import _core, errors
from zalobot._core import API_BASE, DEFAULT_TIMEOUT, NO_RETRY, POLL_TIMEOUT, Call, RetryPolicy
from zalobot.text import Text, split_text
from zalobot.types import BotInfo, ChatAction, ParseMode, SentMessage, Update, WebhookCheck, WebhookInfo

T = TypeVar("T")

__all__ = ["AsyncBot", "Bot", "RetryPolicy"]


class _Base:
    def __init__(self, token: str, base_url: str, timeout: float, retry: RetryPolicy | None) -> None:
        self._token = _core.check_token(token)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retry = retry or NO_RETRY
        self._closed = False
        _core.register_token(self._token)

    @property
    def token(self) -> str:
        """The bot token. It is kept out of ``repr()``, error messages and httpx log lines."""
        return self._token

    def _url(self, method: str) -> str:
        return _core.url_for(self.base_url, self._token, method)

    def _timeout(self, call: Call[Any]) -> float:
        return call.timeout if call.timeout is not None else self.timeout

    def _forget_token(self) -> None:
        if not self._closed:
            self._closed = True
            _core.unregister_token(self._token)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r})"


class Bot(_Base):
    """A blocking Zalo bot client.

    >>> with Bot("123:abc") as bot:          # doctest: +SKIP
    ...     me = bot.get_me()
    ...     bot.send_message(chat_id, f"Hi, I'm {me.account_name}")
    """

    def __init__(
        self,
        token: str,
        *,
        base_url: str = API_BASE,
        timeout: float = DEFAULT_TIMEOUT,
        retry: RetryPolicy | None = None,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(token, base_url, timeout, retry)
        self._own_client = client is None
        self._client = client or httpx.Client(transport=transport, timeout=timeout)

    def close(self) -> None:
        if self._own_client:
            self._client.close()
        self._forget_token()

    def __enter__(self) -> Bot:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    def call(self, call: Call[T]) -> T:
        """Run one prepared call with the retry policy. Most code uses the named methods instead."""
        attempt = 1
        while True:
            try:
                return self._once(call)
            except errors.ZaloError as e:
                if e.code in call.empty_on:
                    return call.convert(None)
                if not self.retry.should_retry(e, attempt, call.idempotent):
                    raise
                time.sleep(self.retry.delay(attempt))
                attempt += 1

    def _once(self, call: Call[T]) -> T:
        failure: errors.NetworkError | None = None
        try:
            response = self._client.post(self._url(call.method), json=call.fields, timeout=self._timeout(call))
        except httpx.HTTPError as e:
            failure = _core.network_error(call.method, e, self._token)
        if failure is not None:  # raised outside the except block: no __context__ holding the request (and its URL)
            raise failure
        result = _core.parse_answer(call.method, response.status_code, response.content, self._token)
        return call.convert(result)

    # --- the 11 Bot API methods ---------------------------------------------------------------------------

    def get_me(self) -> BotInfo:
        """Check the token; returns the bot's id, name and type."""
        return self.call(_core.get_me())

    def get_updates(self, timeout: int = POLL_TIMEOUT) -> list[Update]:
        """Long poll for new messages (waits up to ``timeout`` seconds). ``[]`` when nothing came.

        Zalo refuses this while a webhook is set: call :meth:`delete_webhook` first.
        """
        return self.call(_core.get_updates(timeout))

    def set_webhook(self, url: str, secret_token: str) -> WebhookInfo:
        """Send updates to ``url`` (public HTTPS). Zalo puts ``secret_token`` in the ``X-Bot-Api-Secret-Token``
        header of every request. The answer's ``verification`` says whether your URL answered."""
        return self.call(_core.set_webhook(url, secret_token))

    def test_webhook(self) -> WebhookCheck:
        """Ask Zalo to call your webhook now; ``.ok`` is whether it answered 2xx, ``.hint`` what to fix.
        Zalo answers 400 when no webhook is set."""
        return self.call(_core.test_webhook())

    def delete_webhook(self) -> WebhookInfo:
        """Remove the webhook (needed before :meth:`get_updates`). Zalo answers 400 when none is set."""
        return self.call(_core.delete_webhook())

    def get_webhook_info(self) -> WebhookInfo:
        """The current webhook URL; ``""`` when none is set (Zalo answers 404 then, which this turns into ``""``)."""
        return self.call(_core.get_webhook_info())

    def send_message(self, chat_id: str, text: str | Text, parse_mode: ParseMode | str | None = None) -> SentMessage:
        """Send 1 to 2000 characters. Style with ``parse_mode`` ("markdown"/"html") or pass a :class:`Text`."""
        return self.call(_core.send_message(chat_id, text, parse_mode))

    def send_photo(self, chat_id: str, photo: str, caption: str | None = None) -> SentMessage:
        """Send the image at the URL ``photo``, with an optional caption (1 to 2000 characters)."""
        return self.call(_core.send_photo(chat_id, photo, caption))

    def send_sticker(self, chat_id: str, sticker: str) -> SentMessage:
        """Send a sticker by id (from https://stickers.zaloapp.com/)."""
        return self.call(_core.send_sticker(chat_id, sticker))

    def send_voice(self, chat_id: str, voice_url: str) -> SentMessage:
        """Send the ``.aac`` file at ``voice_url`` as a voice message (1-to-1 chats only)."""
        return self.call(_core.send_voice(chat_id, voice_url))

    def send_chat_action(self, chat_id: str, action: ChatAction | str = ChatAction.TYPING) -> bool:
        """Show "typing..." (or another action) in the chat for a moment."""
        return self.call(_core.send_chat_action(chat_id, action))

    # --- helpers --------------------------------------------------------------------------------------------

    def send_long_message(
        self, chat_id: str, text: str, parse_mode: ParseMode | str | None = None
    ) -> list[SentMessage]:
        """Send text of any length as several messages cut at line breaks."""
        return [self.send_message(chat_id, piece, parse_mode) for piece in split_text(text)]


class AsyncBot(_Base):
    """An asyncio Zalo bot client; the same methods as :class:`Bot`, awaited.

    >>> async with AsyncBot("123:abc") as bot:   # doctest: +SKIP
    ...     await bot.send_message(chat_id, "Xin chào!")
    """

    def __init__(
        self,
        token: str,
        *,
        base_url: str = API_BASE,
        timeout: float = DEFAULT_TIMEOUT,
        retry: RetryPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(token, base_url, timeout, retry)
        self._own_client = client is None
        self._client = client or httpx.AsyncClient(transport=transport, timeout=timeout)

    async def close(self) -> None:
        if self._own_client:
            await self._client.aclose()
        self._forget_token()

    async def __aenter__(self) -> AsyncBot:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self.close()

    async def call(self, call: Call[T]) -> T:
        attempt = 1
        while True:
            try:
                return await self._once(call)
            except errors.ZaloError as e:
                if e.code in call.empty_on:
                    return call.convert(None)
                if not self.retry.should_retry(e, attempt, call.idempotent):
                    raise
                await asyncio.sleep(self.retry.delay(attempt))
                attempt += 1

    async def _once(self, call: Call[T]) -> T:
        failure: errors.NetworkError | None = None
        try:
            response = await self._client.post(self._url(call.method), json=call.fields, timeout=self._timeout(call))
        except httpx.HTTPError as e:
            failure = _core.network_error(call.method, e, self._token)
        if failure is not None:
            raise failure
        result = _core.parse_answer(call.method, response.status_code, response.content, self._token)
        return call.convert(result)

    async def get_me(self) -> BotInfo:
        return await self.call(_core.get_me())

    async def get_updates(self, timeout: int = POLL_TIMEOUT) -> list[Update]:
        return await self.call(_core.get_updates(timeout))

    async def set_webhook(self, url: str, secret_token: str) -> WebhookInfo:
        return await self.call(_core.set_webhook(url, secret_token))

    async def test_webhook(self) -> WebhookCheck:
        return await self.call(_core.test_webhook())

    async def delete_webhook(self) -> WebhookInfo:
        return await self.call(_core.delete_webhook())

    async def get_webhook_info(self) -> WebhookInfo:
        return await self.call(_core.get_webhook_info())

    async def send_message(
        self, chat_id: str, text: str | Text, parse_mode: ParseMode | str | None = None
    ) -> SentMessage:
        return await self.call(_core.send_message(chat_id, text, parse_mode))

    async def send_photo(self, chat_id: str, photo: str, caption: str | None = None) -> SentMessage:
        return await self.call(_core.send_photo(chat_id, photo, caption))

    async def send_sticker(self, chat_id: str, sticker: str) -> SentMessage:
        return await self.call(_core.send_sticker(chat_id, sticker))

    async def send_voice(self, chat_id: str, voice_url: str) -> SentMessage:
        return await self.call(_core.send_voice(chat_id, voice_url))

    async def send_chat_action(self, chat_id: str, action: ChatAction | str = ChatAction.TYPING) -> bool:
        return await self.call(_core.send_chat_action(chat_id, action))

    async def send_long_message(
        self, chat_id: str, text: str, parse_mode: ParseMode | str | None = None
    ) -> list[SentMessage]:
        return [await self.send_message(chat_id, piece, parse_mode) for piece in split_text(text)]
