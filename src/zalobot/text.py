"""Rich text for ``sendMessage`` and splitting long text.

Zalo takes styles in one of two ways (https://bot.zaloplatforms.com/docs/apis/sendMessage/):

- ``parse_mode`` = ``"markdown"`` or ``"html"``: the server reads markup inside ``text``;
- ``text_styles``: a list of ``{"start", "len", "st"}`` runs over the raw text, where ``start`` and ``len`` count
  **UTF-16 code units** (string indexes as in JavaScript/Java), not Python characters.

:class:`Text` builds the second form and does the UTF-16 counting, so Vietnamese diacritics and emoji land where
you expect.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

TEXT_LIMIT = 2000  # sendMessage: 1 to 2000 characters


class Color(StrEnum):
    DEFAULT = "c_050a19"
    GREEN = "c_15a85f"
    YELLOW = "c_f7b503"
    ORANGE = "c_f27806"
    RED = "c_db342e"


class Size(StrEnum):
    SMALL = "f_13"
    NORMAL = "f_15"
    LARGE = "f_18"
    XLARGE = "f_20"


BOLD, ITALIC, UNDERLINE, STRIKE = "b", "i", "u", "s"
BULLET_LIST, NUMBERED_LIST = "lst_1", "lst_2"
STYLE_CODES = frozenset(
    {BOLD, ITALIC, UNDERLINE, STRIKE, BULLET_LIST, NUMBERED_LIST}
    | {c.value for c in Color}
    | {s.value for s in Size}
    | {f"ind_{n}" for n in range(1, 6)}
)


def _by_name(enum: type[StrEnum], value: StrEnum | str) -> str:
    """An enum member given itself or its name in any case; anything else is passed on (``add`` rejects it)."""
    if isinstance(value, str) and value.upper() in enum.__members__:
        return str(enum[value.upper()].value)
    return str(value.value if isinstance(value, StrEnum) else value)


def utf16_len(text: str) -> int:
    """Length in UTF-16 code units: characters outside the BMP (most emoji) count 2."""
    return len(text.encode("utf-16-le")) // 2


def indent(level: int) -> str:
    if not 1 <= level <= 5:
        raise ValueError("indent level must be 1 to 5")
    return f"ind_{level}"


class Text:
    """A message built piece by piece, each piece with its own styles.

    >>> t = Text().bold("Đơn hàng #12").plain(" đã giao ").color(Color.GREEN, "✅")
    >>> t.text
    'Đơn hàng #12 đã giao ✅'
    >>> t.styles
    [{'start': 0, 'len': 12, 'st': ['b']}, {'start': 21, 'len': 1, 'st': ['c_15a85f']}]
    """

    def __init__(self, text: str = "") -> None:
        self._parts: list[str] = []
        self._units = 0
        self._styles: list[dict[str, Any]] = []
        if text:
            self.plain(text)

    # --- building -------------------------------------------------------------------------------------------

    def add(self, text: str, *styles: str) -> Text:
        """Append ``text`` with the given style codes (``"b"``, ``Color.RED``, ``Size.LARGE``, ``"ind_2"`` ...)."""
        if not isinstance(text, str):
            raise TypeError("text must be a str")
        codes = [str(s.value if isinstance(s, StrEnum) else s) for s in styles]
        unknown = [c for c in codes if c not in STYLE_CODES]
        if unknown:
            raise ValueError(f"unknown style code(s) {unknown}; Zalo ignores codes outside its list")
        length = utf16_len(text)
        if codes and length:
            self._styles.append({"start": self._units, "len": length, "st": codes})
        self._parts.append(text)
        self._units += length
        return self

    def plain(self, text: str) -> Text:
        return self.add(text)

    def bold(self, text: str) -> Text:
        return self.add(text, BOLD)

    def italic(self, text: str) -> Text:
        return self.add(text, ITALIC)

    def underline(self, text: str) -> Text:
        return self.add(text, UNDERLINE)

    def strike(self, text: str) -> Text:
        return self.add(text, STRIKE)

    def color(self, color: Color | str, text: str) -> Text:
        """``color(Color.RED, ...)`` or by name: ``color("red", ...)``."""
        return self.add(text, _by_name(Color, color))

    def size(self, size: Size | str, text: str) -> Text:
        """``size(Size.LARGE, ...)`` or by name: ``size("large", ...)``."""
        return self.add(text, _by_name(Size, size))

    def line(self, text: str = "", *styles: str) -> Text:
        """Append ``text`` plus a line break (the break itself is unstyled)."""
        self.add(text, *styles)
        return self.add("\n")

    def bullets(self, items: Iterable[str]) -> Text:
        """One bulleted line per item."""
        for item in items:
            self.line(item, BULLET_LIST)
        return self

    def numbered(self, items: Iterable[str]) -> Text:
        """One numbered line per item."""
        for item in items:
            self.line(item, NUMBERED_LIST)
        return self

    # --- output ---------------------------------------------------------------------------------------------

    @property
    def text(self) -> str:
        return "".join(self._parts)

    @property
    def styles(self) -> list[dict[str, Any]]:
        return [dict(s, st=list(s["st"])) for s in self._styles]

    def to_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {"text": self.text}
        if self._styles:
            fields["text_styles"] = self.styles
        return fields

    def __len__(self) -> int:
        return len(self.text)

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return f"Text({self.text!r}, styles={len(self._styles)})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Text) and self.to_fields() == other.to_fields()

    __hash__ = None  # type: ignore[assignment]


def _cut(line: str, limit: int) -> tuple[str, str]:
    """The longest head of ``line`` within ``limit`` UTF-16 units (never half of a surrogate pair), and the rest."""
    units = 0
    for i, char in enumerate(line):
        units += 2 if ord(char) > 0xFFFF else 1
        if units > limit:
            return line[:i], line[i:]
    return line, ""


def split_text(text: str, limit: int = TEXT_LIMIT) -> list[str]:
    """Cut ``text`` at line breaks into pieces of at most ``limit`` UTF-16 units (Zalo's server counts Java string
    length, where most emoji take 2).

    A single line longer than ``limit`` is cut hard, never inside an emoji. Blank pieces are dropped; ``""`` gives
    ``[]``.
    """
    if limit < 2:
        raise ValueError("limit must be at least 2")
    pieces: list[str] = []
    current, current_len = "", 0
    for line in text.split("\n"):
        line_len = utf16_len(line)
        while line_len > limit:
            if current:
                pieces.append(current)
                current, current_len = "", 0
            head, line = _cut(line, limit)
            pieces.append(head)
            line_len = utf16_len(line)
        if current and current_len + 1 + line_len > limit:
            pieces.append(current)
            current, current_len = line, line_len
        elif current:
            current, current_len = f"{current}\n{line}", current_len + 1 + line_len
        else:
            current, current_len = line, line_len
    if current:
        pieces.append(current)
    return [p for p in pieces if p.strip()]
