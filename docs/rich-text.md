# Rich text

`sendMessage` takes styles in two forms. If you send both, Zalo uses `parse_mode` and ignores `text_styles`, so
zalobot refuses that combination.

## Let Zalo parse markup

```python
bot.send_message(chat_id, "**bold** _italic_ ~~strike~~ {red}red{/red} {big}big{/big}", parse_mode="markdown")
bot.send_message(chat_id, "<b>bold</b> <i>italic</i> <u>underline</u>", parse_mode="html")
```

Markdown supports `**bold**`, `*italic*`, `~~strike~~`, `` `code` ``, `#` headings, `-` and `1.` lists, `>`
indents, the colours `{red}`, `{orange}`, `{yellow}` and `{green}`, plus `{big}` and `{underline}`. HTML supports
`b`/`strong`, `i`/`em`, `u`, `s`/`del`, `h1` to `h6`, `ul`/`ol`/`li` and `p`/`div`.

## Build styles with `Text`

```python
from zalobot import Color, Size, Text

msg = (
    Text()
    .size(Size.LARGE, "Đơn hàng #1024").plain("\n")
    .bullets(["Cà phê sữa đá: 29,000đ", "Bánh mì: 25,000đ"])
    .bold("Tổng: ").plain("54,000đ ")
    .color(Color.GREEN, "✅ đã thanh toán")
)
bot.send_message(chat_id, msg)
```

Zalo's `text_styles` positions count **UTF-16 code units**, as JavaScript and Java strings do. Python counts code
points instead, so most emoji are 1 in Python but 2 in UTF-16. Hand-computed offsets therefore drift after the
first emoji, and Vietnamese text written with combining accents shifts them further. `Text` counts in UTF-16 for
you.

| Method | Style |
|---|---|
| `bold`, `italic`, `underline`, `strike` | `b`, `i`, `u`, `s` |
| `size(Size.SMALL / NORMAL / LARGE / XLARGE, ...)` | `f_13`, `f_15`, `f_18`, `f_20` |
| `color(Color.RED / ORANGE / YELLOW / GREEN / DEFAULT, ...)` | `c_db342e`, ... |
| `bullets([...])`, `numbered([...])` | `lst_1`, `lst_2` |
| `add(text, "b", Color.RED, indent(2))` | any combination |

## Long text

A message holds at most 2,000 characters. `bot.send_long_message(chat_id, text)` or `ctx.reply_long(text)` splits
longer text at line breaks. Use `zalobot.split_text(text)` if you only want the pieces.
