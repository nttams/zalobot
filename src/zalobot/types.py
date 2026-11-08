"""Typed views of the Bot API's JSON (https://bot.zaloplatforms.com/docs/).

Every object keeps the JSON it was built from in ``raw``, so a field Zalo adds later is still reachable before this
library knows about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

JSON = dict[str, Any]


class EventName(StrEnum):
    TEXT = "message.text.received"
    IMAGE = "message.image.received"
    STICKER = "message.sticker.received"
    VOICE = "message.voice.received"
    # The sender is in a protected group (children, people with disabilities, ...): Zalo withholds the content.
    UNSUPPORTED = "message.unsupported.received"


class ChatType(StrEnum):
    PRIVATE = "PRIVATE"
    GROUP = "GROUP"  # beta: in a group the bot only sees @mentions and replies to its own messages


class ChatAction(StrEnum):
    TYPING = "typing"
    UPLOAD_PHOTO = "upload_photo"  # "coming soon" in the docs


class ParseMode(StrEnum):
    MARKDOWN = "markdown"
    HTML = "html"


def _split_command(text: str | None) -> tuple[str | None, str]:
    if not text or not text.startswith("/"):
        return None, ""
    parts = text[1:].split(maxsplit=1)
    if not parts:
        return None, ""
    return parts[0].lower(), parts[1] if len(parts) > 1 else ""


def _ms(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


@dataclass(frozen=True)
class User:
    id: str
    display_name: str = ""
    is_bot: bool = False
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: JSON | None) -> User:
        d = d or {}
        return cls(
            id=str(d.get("id") or ""),
            display_name=d.get("display_name") or "",
            is_bot=bool(d.get("is_bot")),
            raw=d,
        )


@dataclass(frozen=True)
class Chat:
    id: str
    chat_type: str = ChatType.PRIVATE.value
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @property
    def is_private(self) -> bool:
        return self.chat_type == ChatType.PRIVATE.value

    @property
    def is_group(self) -> bool:
        return self.chat_type == ChatType.GROUP.value

    @classmethod
    def from_dict(cls, d: JSON | None) -> Chat:
        d = d or {}
        return cls(id=str(d.get("id") or ""), chat_type=d.get("chat_type") or "", raw=d)


@dataclass(frozen=True)
class Message:
    message_id: str
    date: datetime | None
    from_user: User
    chat: Chat
    message_type: str = ""  # CHAT_TEXT, CHAT_PHOTO, CHAT_STICKER, CHAT_VOICE
    text: str | None = None
    photo_url: str | None = None
    caption: str | None = None
    sticker: str | None = None
    sticker_url: str | None = None  # the JSON field is "url"
    voice_url: str | None = None
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: JSON | None) -> Message:
        d = d or {}
        return cls(
            message_id=str(d.get("message_id") or ""),
            date=_ms(d.get("date")),
            from_user=User.from_dict(d.get("from")),
            chat=Chat.from_dict(d.get("chat")),
            message_type=d.get("message_type") or "",
            text=d.get("text"),
            photo_url=d.get("photo_url"),
            caption=d.get("caption"),
            sticker=d.get("sticker"),
            sticker_url=d.get("url"),
            voice_url=d.get("voice_url"),
            raw=d,
        )


@dataclass(frozen=True)
class Update:
    """One event, from ``getUpdates`` or a webhook POST (both have the same body)."""

    event_name: str
    message: Message | None
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @property
    def is_text(self) -> bool:
        return self.event_name == EventName.TEXT.value

    @property
    def text(self) -> str | None:
        return self.message.text if self.message else None

    @property
    def command(self) -> str | None:
        """``"/add 50k coffee"`` -> ``"add"`` (lower case); ``None`` for a message that is not a command."""
        word, _ = _split_command(self.text)
        return word

    @property
    def args(self) -> str:
        """The text after the command word (``"50k coffee"``), ``""`` if none."""
        _, rest = _split_command(self.text)
        return rest

    @classmethod
    def from_dict(cls, d: JSON) -> Update:
        m = d.get("message")
        return cls(event_name=d.get("event_name") or "", message=Message.from_dict(m) if m else None, raw=d)


@dataclass(frozen=True)
class BotInfo:
    id: str
    account_name: str
    account_type: str = ""
    can_join_groups: bool = False
    display_name: str = ""  # not in the docs; the real API returns it
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: JSON) -> BotInfo:
        return cls(
            id=str(d.get("id") or ""),
            account_name=d.get("account_name") or "",
            account_type=d.get("account_type") or "",
            can_join_groups=bool(d.get("can_join_groups")),
            display_name=d.get("display_name") or "",
            raw=d,
        )


@dataclass(frozen=True)
class SentMessage:
    message_id: str
    date: datetime | None
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: JSON | None) -> SentMessage:
        d = d or {}
        return cls(message_id=str(d.get("message_id") or ""), date=_ms(d.get("date")), raw=d)


@dataclass(frozen=True)
class WebhookCheck:
    """``testWebhook``'s result, also ``setWebhook``'s ``verification``. ``ok`` is whether *your URL* answered 2xx."""

    ok: bool
    url: str
    outcome: str  # webhook.ok, webhook.http.403, webhook.http.404, webhook.http.5xx, webhook.err.tls, ...
    hint: str = ""
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: JSON | None) -> WebhookCheck:
        d = d or {}
        return cls(
            ok=bool(d.get("ok")),
            url=d.get("url") or "",
            outcome=d.get("outcome") or "",
            hint=d.get("hint") or "",
            raw=d,
        )


@dataclass(frozen=True)
class WebhookInfo:
    url: str  # "" when no webhook is set
    updated_at: datetime | None
    verification: WebhookCheck | None = None  # only on setWebhook's answer
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: JSON | None) -> WebhookInfo:
        d = d or {}
        v = d.get("verification")
        return cls(
            url=d.get("url") or "",
            updated_at=_ms(d.get("updated_at")),
            verification=WebhookCheck.from_dict(v) if v else None,
            raw=d,
        )
