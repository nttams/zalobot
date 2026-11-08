"""Errors raised for a Zalo Bot API answer of ``{"ok": false, "error_code": N, "description": "..."}``.

Codes from the official error table (https://bot.zaloplatforms.com/docs/error-code/), plus 410, which the real API
uses for an unknown chat. The real API answers errors with HTTP 200 and the code in the body.
"""

from __future__ import annotations

from typing import Any


class ZaloError(Exception):
    """Any failed Bot API call. ``code`` is Zalo's ``error_code`` (``None`` for a network error)."""

    def __init__(self, code: int | None, description: str, method: str = ""):
        self.code, self.description, self.method = code, description, method
        where = f"{method}: " if method else ""
        super().__init__(f"{where}{code} {description}" if code is not None else f"{where}{description}")


class BadRequest(ZaloError):
    """400: wrong path, unknown method or invalid fields."""


class Unauthorized(ZaloError):
    """401: the bot token is expired or invalid. Retrying will not help."""


class Forbidden(ZaloError):
    """403: Zalo's table calls it an internal server error."""


class NotFound(ZaloError):
    """404: the request points at nothing."""


class TimedOut(ZaloError):
    """408: the request took too long. ``getUpdates`` answers it when no message came during its timeout."""


class InvalidChat(ZaloError):
    """410 "The chat_id is invaild": no chat with that id for this bot. Not in Zalo's error table; seen from the
    real API."""


class QuotaExceeded(ZaloError):
    """429: the bot went over its API quota. Wait before calling again."""


class NetworkError(ZaloError):
    """The request never got a Bot API answer (DNS, TLS, connection reset, HTTP timeout).

    ``request_sent`` is False only when the request surely never reached Zalo (the connection or a free
    connection could not be had). When it is True, Zalo may have acted on it: a send may have been delivered.
    """

    def __init__(self, code: int | None, description: str, method: str = "", *, request_sent: bool = True):
        super().__init__(code, description, method)
        self.request_sent = request_sent


_BY_CODE: dict[int, type[ZaloError]] = {
    400: BadRequest,
    401: Unauthorized,
    403: Forbidden,
    404: NotFound,
    408: TimedOut,
    410: InvalidChat,
    429: QuotaExceeded,
}


def from_answer(method: str, answer: dict[str, Any]) -> ZaloError:
    code = answer.get("error_code")
    try:
        code = int(code) if code is not None else None
    except (TypeError, ValueError):
        code = None
    cls = _BY_CODE.get(code, ZaloError) if code is not None else ZaloError
    return cls(code, str(answer.get("description") or "no description"), method)
