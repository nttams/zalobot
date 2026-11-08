"""Receiving updates by webhook, with any web framework.

Zalo POSTs each update as JSON to your URL with the header ``X-Bot-Api-Secret-Token`` set to the
``secret_token`` you gave :meth:`~zalobot.Bot.set_webhook` (https://bot.zaloplatforms.com/docs/webhook/).
Check the header before trusting the body. These helpers do that, so the framework glue stays a few lines:

>>> handler = WebhookHandler(dp, bot, secret="my-secret-token")
>>> status, body = handler.handle(request.headers, request.body)     # doctest: +SKIP
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Mapping
from typing import Any

from zalobot.client import AsyncBot, Bot
from zalobot.dispatcher import Dispatcher
from zalobot.types import Update

__all__ = ["SECRET_HEADER", "AsyncWebhookHandler", "WebhookHandler", "parse_update", "verify_secret"]

SECRET_HEADER = "X-Bot-Api-Secret-Token"  # noqa: S105 (a header name)

OK = (200, b'{"message":"Success"}')
FORBIDDEN = (403, b'{"message":"Unauthorized"}')
BAD_REQUEST = (400, b'{"message":"Bad request"}')


def _header(headers: Mapping[str, str], name: str) -> str | None:
    value = headers.get(name)
    if value is not None:
        return value
    lowered = name.lower()
    for key, val in headers.items():
        if key.lower() == lowered:
            return val
    return None


def verify_secret(headers: Mapping[str, str], secret: str) -> bool:
    """Whether the request carries the right ``X-Bot-Api-Secret-Token`` (constant-time compare)."""
    if not secret:
        raise ValueError("a secret is required to check webhook requests")
    given = _header(headers, SECRET_HEADER)
    return given is not None and hmac.compare_digest(given.encode(), secret.encode())


def parse_update(body: bytes | str | Mapping[str, Any]) -> Update:
    """The update in a webhook body. Raises ValueError for anything that is not a JSON object."""
    if isinstance(body, Mapping):
        data: Any = dict(body)
    else:
        try:
            data = json.loads(body)
        except (TypeError, ValueError) as e:
            raise ValueError(f"webhook body is not JSON: {e}") from None
    if not isinstance(data, dict):
        raise ValueError("webhook body is not a JSON object")
    return Update.from_dict(data)


def _checked_update(headers: Mapping[str, str], body: bytes | str, secret: str) -> Update | tuple[int, bytes]:
    """The update in a request, or the response to send when the request is refused."""
    if not verify_secret(headers, secret):
        return FORBIDDEN
    try:
        return parse_update(body)
    except ValueError:
        return BAD_REQUEST


def _check_secret(secret: str) -> str:
    if not secret or not 8 <= len(secret) <= 256:
        raise ValueError("secret must be the 8 to 256 character secret_token given to set_webhook")
    return secret


class WebhookHandler:
    """Check, parse and dispatch one webhook request with a blocking :class:`~zalobot.Bot`.

    ``handle()`` returns ``(status, body)`` for your framework to send: 403 for a wrong or missing secret, 400 for
    a body that is not an update, 200 otherwise (handler errors go to the dispatcher's error hook, and Zalo still
    gets 200 so it does not keep re-sending a message your code can't handle).
    """

    def __init__(self, dispatcher: Dispatcher, bot: Bot, secret: str) -> None:
        self.dispatcher, self.bot, self.secret = dispatcher, bot, _check_secret(secret)

    def handle(self, headers: Mapping[str, str], body: bytes | str) -> tuple[int, bytes]:
        update = _checked_update(headers, body, self.secret)
        if not isinstance(update, Update):
            return update
        self.dispatcher.feed(self.bot, update)
        return OK


class AsyncWebhookHandler:
    """The asyncio twin of :class:`WebhookHandler`, for ASGI frameworks (FastAPI, Starlette, aiohttp ...)."""

    def __init__(self, dispatcher: Dispatcher, bot: AsyncBot, secret: str) -> None:
        self.dispatcher, self.bot, self.secret = dispatcher, bot, _check_secret(secret)

    async def handle(self, headers: Mapping[str, str], body: bytes | str) -> tuple[int, bytes]:
        update = _checked_update(headers, body, self.secret)
        if not isinstance(update, Update):
            return update
        await self.dispatcher.feed_async(self.bot, update)
        return OK
