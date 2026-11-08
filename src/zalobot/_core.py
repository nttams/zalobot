"""What the sync and async clients share: request building, answer parsing, validation, retries, redaction.

Every Bot API call is ``POST {base_url}/bot<TOKEN>/<method>`` with a JSON body; the answer is
``{"ok": true, "result": ...}`` or ``{"ok": false, "error_code": N, "description": "..."}``.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import httpx

from zalobot import errors
from zalobot.text import TEXT_LIMIT, Text, utf16_len
from zalobot.types import (
    JSON,
    BotInfo,
    ChatAction,
    ParseMode,
    SentMessage,
    Update,
    WebhookCheck,
    WebhookInfo,
)

API_BASE = "https://bot-api.zaloplatforms.com"
DEFAULT_TIMEOUT = 30.0
POLL_TIMEOUT = 30  # getUpdates' own default wait, in seconds
_POLL_HTTP_MARGIN = 10.0  # the HTTP request waits this much longer than the long poll

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Retry 429 (quota) and network errors with doubling waits. 401 and other API errors are never retried.

    ``attempts`` counts every try, so ``attempts=1`` means no retry (the default when no policy is given).
    """

    attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    retry_network: bool = True

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("attempts must be at least 1")

    def should_retry(self, error: errors.ZaloError, attempt: int, idempotent: bool = True) -> bool:
        """Quota errors are always safe to retry (Zalo refused the call). A network error is retried for reads, and
        for sends only when the request never left: retrying a send Zalo may have delivered would send it twice."""
        if attempt >= self.attempts:
            return False
        if isinstance(error, errors.QuotaExceeded):
            return True
        if not self.retry_network or not isinstance(error, errors.NetworkError):
            return False
        return idempotent or not error.request_sent

    def delay(self, attempt: int) -> float:
        return float(min(self.max_delay, self.base_delay * 2 ** (attempt - 1)))


NO_RETRY = RetryPolicy(attempts=1)


@dataclass(frozen=True)
class Call(Generic[T]):
    """One prepared API call: the method, its JSON fields and how to turn ``result`` into a typed value."""

    method: str
    fields: JSON
    convert: Callable[[Any], T]
    timeout: float | None = None  # None = the client's timeout
    # Error codes that mean "nothing" rather than failure: the call returns convert(None). getUpdates: 408 = no
    # message came. getWebhookInfo: 404 = no webhook is set (the real API; the docs show url "").
    empty_on: frozenset[int] = frozenset()
    idempotent: bool = True  # False for sends: repeating one after it may have arrived sends it twice


def redact(text: str, token: str) -> str:
    return text.replace(token, "<token>") if token else text


class _RedactFilter(logging.Filter):
    """httpx logs every request URL at INFO level, and the URL holds the bot token: hide it."""

    def __init__(self) -> None:
        super().__init__()
        self._tokens: dict[str, int] = {}
        self._lock = threading.Lock()

    def add(self, token: str) -> None:
        with self._lock:
            self._tokens[token] = self._tokens.get(token, 0) + 1

    def remove(self, token: str) -> None:
        with self._lock:
            n = self._tokens.get(token, 0) - 1
            if n > 0:
                self._tokens[token] = n
            else:
                self._tokens.pop(token, None)

    def filter(self, record: logging.LogRecord) -> bool:
        tokens = list(self._tokens)
        if not tokens:
            return True
        message = record.getMessage()
        cleaned = message
        for token in tokens:
            cleaned = cleaned.replace(token, "<token>")
        if cleaned != message:
            record.msg, record.args = cleaned, None
        return True


_redact_filter = _RedactFilter()
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).addFilter(_redact_filter)


def register_token(token: str) -> None:
    _redact_filter.add(token)


def unregister_token(token: str) -> None:
    _redact_filter.remove(token)


class Token(str):
    """The bot token: a plain ``str`` whose ``repr()`` is masked, so tracebacks that print locals don't show it."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "'<token>'"


def check_token(token: str) -> Token:
    if not isinstance(token, str) or not token.strip():
        raise ValueError("a bot token is required (Zalo sends it when you create the bot)")
    if any(c.isspace() or c == "/" for c in token):
        raise ValueError("the bot token must not contain spaces or '/'")
    return Token(token)


def url_for(base_url: str, token: str, method: str) -> str:
    return f"{base_url.rstrip('/')}/bot{token}/{method}"


def parse_answer(method: str, status_code: int, content: bytes, token: str) -> Any:
    """-> ``result`` of a successful answer; raises the matching ZaloError otherwise."""
    if token and content:
        content = content.replace(token.encode(), b"<token>")
    try:
        answer = json.loads(content) if content else {}
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        raise errors.from_answer(
            method,
            {
                "error_code": status_code,
                "description": redact(f"answer is not JSON (HTTP {status_code})", token),
            },
        )
    if answer.get("ok") is True:
        return answer.get("result")
    if answer.get("error_code") is None and status_code >= 400:
        answer = {**answer, "error_code": status_code}
    answer = {**answer, "description": redact(str(answer.get("description") or "no description"), token)}
    raise errors.from_answer(method, answer)


# The request surely never reached Zalo: no connection could be made, or none was free in the pool.
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


def network_error(method: str, exc: Exception, token: str) -> errors.NetworkError:
    return errors.NetworkError(
        None,
        redact(f"{type(exc).__name__}: {exc}", token),
        method,
        request_sent=not isinstance(exc, _NOT_SENT),
    )


# --- validation (limits from the official method pages) -------------------------------------------------------


def _check_length(name: str, value: str, low: int, high: int, *, utf16: bool = False) -> None:
    """``utf16``: count like Zalo's Java server (``String.length()``), where most emoji take 2."""
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str")
    length = utf16_len(value) if utf16 else len(value)
    if not low <= length <= high:
        unit = "UTF-16 units" if utf16 and length != len(value) else "characters"
        raise ValueError(f"{name} is {length} {unit}; Zalo takes {low} to {high}")


def _check_chat(chat_id: str) -> str:
    chat = str(chat_id)
    if not chat.strip():
        raise ValueError("chat_id is required")
    return chat


# --- calls ------------------------------------------------------------------------------------------------------


def _true(_: Any) -> bool:
    return True


def _updates(result: Any) -> list[Update]:
    """The docs show one event per ``result``; a list (or nothing) is accepted too."""
    if not result:
        return []
    events = result if isinstance(result, list) else [result]
    return [Update.from_dict(e) for e in events if isinstance(e, dict)]


def get_me() -> Call[BotInfo]:
    return Call("getMe", {}, lambda r: BotInfo.from_dict(r or {}))


def get_updates(timeout: int = POLL_TIMEOUT) -> Call[list[Update]]:
    if not 0 <= int(timeout) <= 600:
        raise ValueError("timeout must be between 0 and 600 seconds")
    return Call(
        "getUpdates",
        {"timeout": str(int(timeout))},
        _updates,
        timeout=int(timeout) + _POLL_HTTP_MARGIN,
        empty_on=frozenset({408}),
    )


def set_webhook(url: str, secret_token: str) -> Call[WebhookInfo]:
    if not isinstance(url, str) or not url.lower().startswith("https://"):
        raise ValueError("the webhook url must be a public https:// URL")
    _check_length("secret_token", secret_token, 8, 256)
    return Call("setWebhook", {"url": url, "secret_token": secret_token}, WebhookInfo.from_dict)


def test_webhook() -> Call[WebhookCheck]:
    return Call("testWebhook", {}, WebhookCheck.from_dict)


def delete_webhook() -> Call[WebhookInfo]:
    return Call("deleteWebhook", {}, WebhookInfo.from_dict)


def get_webhook_info() -> Call[WebhookInfo]:
    return Call("getWebhookInfo", {}, WebhookInfo.from_dict, empty_on=frozenset({404}))


def send_message(chat_id: str, text: str | Text, parse_mode: ParseMode | str | None = None) -> Call[SentMessage]:
    fields: JSON = {"chat_id": _check_chat(chat_id)}
    if isinstance(text, Text):
        if parse_mode is not None:
            raise ValueError("pass either parse_mode or a Text with styles, not both (Zalo would ignore the styles)")
        fields.update(text.to_fields())
    else:
        fields["text"] = text
        if parse_mode is not None:
            fields["parse_mode"] = ParseMode(parse_mode).value
    _check_length("text", fields["text"], 1, TEXT_LIMIT, utf16=True)
    return Call("sendMessage", fields, SentMessage.from_dict, idempotent=False)


def send_photo(chat_id: str, photo: str, caption: str | None = None) -> Call[SentMessage]:
    if not isinstance(photo, str) or not photo.lower().startswith(("http://", "https://")):
        raise ValueError("photo must be an http(s) URL of the image (Zalo fetches it)")
    fields: JSON = {"chat_id": _check_chat(chat_id), "photo": photo}
    if caption is not None:
        _check_length("caption", caption, 1, TEXT_LIMIT, utf16=True)
        fields["caption"] = caption
    return Call("sendPhoto", fields, SentMessage.from_dict, idempotent=False)


def send_sticker(chat_id: str, sticker: str) -> Call[SentMessage]:
    if not isinstance(sticker, str) or not sticker.strip():
        raise ValueError("sticker is required (an id from https://stickers.zaloapp.com/)")
    return Call(
        "sendSticker", {"chat_id": _check_chat(chat_id), "sticker": sticker}, SentMessage.from_dict, idempotent=False
    )


def send_voice(chat_id: str, voice_url: str) -> Call[SentMessage]:
    """1-to-1 chats only: Zalo answers ok for a group id but delivers nothing."""
    if not isinstance(voice_url, str) or not voice_url.lower().startswith(("http://", "https://")):
        raise ValueError("voice_url must be an http(s) URL")
    if not voice_url.lower().split("?", 1)[0].endswith(".aac"):
        raise ValueError("voice_url must point to an .aac file (the only format Zalo supports)")
    return Call(
        "sendVoice", {"chat_id": _check_chat(chat_id), "voice_url": voice_url}, SentMessage.from_dict, idempotent=False
    )


def send_chat_action(chat_id: str, action: ChatAction | str = ChatAction.TYPING) -> Call[bool]:
    return Call("sendChatAction", {"chat_id": _check_chat(chat_id), "action": ChatAction(action).value}, _true)
