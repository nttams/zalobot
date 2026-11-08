"""Filters pick which updates a handler gets. Combine them with ``&``, ``|`` and ``~``.

>>> from zalobot.filters import F
>>> wanted = F.text & F.private & ~F.regex(r"^/")
"""

from __future__ import annotations

import re
from collections.abc import Callable

from zalobot.types import ChatType, EventName, Update

__all__ = ["F", "Filter"]


class Filter:
    """A named test on an :class:`~zalobot.types.Update`."""

    def __init__(self, test: Callable[[Update], bool], name: str = "filter") -> None:
        self._test = test
        self.name = name

    def __call__(self, update: Update) -> bool:
        return bool(self._test(update))

    def __and__(self, other: Filter) -> Filter:
        return Filter(lambda u: self(u) and other(u), f"({self.name} & {other.name})")

    def __or__(self, other: Filter) -> Filter:
        return Filter(lambda u: self(u) or other(u), f"({self.name} | {other.name})")

    def __invert__(self) -> Filter:
        return Filter(lambda u: not self(u), f"~{self.name}")

    def __repr__(self) -> str:
        return f"Filter({self.name})"


def _event(name: EventName) -> Filter:
    return Filter(lambda u: u.event_name == name.value, name.name.lower())


def _chat_type(kind: ChatType) -> Filter:
    return Filter(lambda u: u.message is not None and u.message.chat.chat_type == kind.value, kind.value.lower())


def _command(*names: str) -> Filter:
    wanted = {n.lower().lstrip("/") for n in names}
    if not wanted:
        return Filter(lambda u: u.command is not None, "command")
    return Filter(lambda u: u.command in wanted, f"command{sorted(wanted)}")


def _regex(pattern: str | re.Pattern[str], flags: int = 0) -> Filter:
    compiled = re.compile(pattern, flags) if isinstance(pattern, str) else pattern

    def test(u: Update) -> bool:
        m = u.message
        value = m.text if m and m.text is not None else (m.caption if m else None)
        return value is not None and compiled.search(value) is not None

    return Filter(test, f"regex({compiled.pattern!r})")


def _from_user(*user_ids: str) -> Filter:
    ids = {str(i) for i in user_ids}
    return Filter(lambda u: u.message is not None and u.message.from_user.id in ids, "from_user")


def _chat(*chat_ids: str) -> Filter:
    ids = {str(i) for i in chat_ids}
    return Filter(lambda u: u.message is not None and u.message.chat.id in ids, "chat")


class F:
    """Ready-made filters."""

    all = Filter(lambda u: True, "all")
    text = _event(EventName.TEXT)
    photo = _event(EventName.IMAGE)
    sticker = _event(EventName.STICKER)
    voice = _event(EventName.VOICE)
    unsupported = _event(EventName.UNSUPPORTED)
    private = _chat_type(ChatType.PRIVATE)
    group = _chat_type(ChatType.GROUP)
    command = staticmethod(_command)
    regex = staticmethod(_regex)
    from_user = staticmethod(_from_user)
    chat = staticmethod(_chat)
