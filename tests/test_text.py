from __future__ import annotations

import unicodedata

import pytest

from zalobot.text import Color, Size, Text, indent, split_text, utf16_len


def _slice16(text: str, start: int, length: int) -> str:
    """What a JavaScript/Java client shows for a UTF-16 (start, len) run."""
    units = text.encode("utf-16-le")
    return units[start * 2 : (start + length) * 2].decode("utf-16-le")


def test_docs_example() -> None:
    t = Text().add("Xin chào", "b", Color.RED).plain(" bạn")
    assert t.to_fields() == {
        "text": "Xin chào bạn",
        "text_styles": [{"start": 0, "len": 8, "st": ["b", "c_db342e"]}],
    }


def test_vietnamese_precomposed_and_emoji_offsets() -> None:
    t = Text().bold("Đơn hàng #12").plain(" 🎉🎉 ").color("green", "đã giao ✅").plain(" ").italic("Trần Thị Ánh")
    assert t.text == "Đơn hàng #12 🎉🎉 đã giao ✅ Trần Thị Ánh"
    runs = t.styles
    assert [_slice16(t.text, r["start"], r["len"]) for r in runs] == ["Đơn hàng #12", "đã giao ✅", "Trần Thị Ánh"]
    # Python indexes and UTF-16 indexes differ after the emoji (each is 2 code units)
    assert runs[1]["start"] == t.text.index("đã") + 2


def test_combining_diacritics() -> None:
    decomposed = unicodedata.normalize("NFD", "Nguyễn")
    assert len(decomposed) > len("Nguyễn")
    t = Text().plain("👋 ").bold(decomposed)
    [run] = t.styles
    assert run["start"] == 3 and run["len"] == len(decomposed)
    assert _slice16(t.text, run["start"], run["len"]) == decomposed


def test_utf16_len() -> None:
    assert utf16_len("abc") == 3
    assert utf16_len("ắ") == 1
    assert utf16_len("😀") == 2
    assert utf16_len("👨‍👩‍👧") == 8


def test_all_style_codes() -> None:
    t = (
        Text()
        .bold("b")
        .italic("i")
        .underline("u")
        .strike("s")
        .size(Size.SMALL, "1")
        .size("normal", "2")
        .size("large", "3")
        .size(Size.XLARGE, "4")
        .color(Color.DEFAULT, "d")
        .color("yellow", "y")
        .color("orange", "o")
        .color(Color.RED, "r")
        .add("x", indent(1))
        .add("x", indent(5))
    )
    codes = [s["st"][0] for s in t.styles]
    assert codes == [
        "b",
        "i",
        "u",
        "s",
        "f_13",
        "f_15",
        "f_18",
        "f_20",
        "c_050a19",
        "c_f7b503",
        "c_f27806",
        "c_db342e",
        "ind_1",
        "ind_5",
    ]
    with pytest.raises(ValueError):
        indent(6)


def test_lists() -> None:
    t = Text().line("Món:", "b").bullets(["Phở", "Bún chả"]).numbered(["một"])
    assert t.text == "Món:\nPhở\nBún chả\nmột\n"
    assert [(s["st"], _slice16(t.text, s["start"], s["len"])) for s in t.styles] == [
        (["b"], "Món:"),
        (["lst_1"], "Phở"),
        (["lst_1"], "Bún chả"),
        (["lst_2"], "một"),
    ]


def test_unknown_code_and_type() -> None:
    with pytest.raises(ValueError, match="unknown style"):
        Text().add("x", "blink")
    with pytest.raises(ValueError, match="unknown style"):
        Text().color("purple", "x")
    with pytest.raises(TypeError):
        Text().add(5)  # type: ignore[arg-type]


def test_plain_text_has_no_styles() -> None:
    t = Text("chỉ chữ")
    assert t.to_fields() == {"text": "chỉ chữ"}
    assert str(t) == "chỉ chữ" and len(t) == 7
    assert "styles=0" in repr(t)


def test_empty_styled_piece_is_skipped() -> None:
    assert Text().bold("").plain("x").styles == []


def test_equality_and_copy() -> None:
    a, b = Text().bold("x"), Text().bold("x")
    assert a == b and a != Text("x") and a != "x"
    a.styles[0]["st"].append("i")
    assert a.styles == [{"start": 0, "len": 1, "st": ["b"]}]


def test_split_text() -> None:
    assert split_text("") == []
    assert split_text("short") == ["short"]
    assert split_text("a\nb\nc", limit=3) == ["a\nb", "c"]
    assert split_text("x" * 7, limit=3) == ["xxx", "xxx", "x"]
    assert split_text("ab\n" + "x" * 5 + "\ncd", limit=3) == ["ab", "xxx", "xx", "cd"]
    assert split_text("ab\n" + "x" * 5 + "\nc", limit=4) == ["ab", "xxxx", "x\nc"]
    assert split_text("\n\n  \n") == []
    long = "\n".join("dòng " + str(i) * 50 for i in range(100))
    pieces = split_text(long)
    assert all(len(p) <= 2000 for p in pieces) and "\n".join(pieces) == long
    with pytest.raises(ValueError):
        split_text("x", limit=0)
