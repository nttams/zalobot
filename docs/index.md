# zalobot

A typed Python library for the [Zalo Bot Platform](https://bot.zaloplatforms.com/docs/): blocking and asyncio
clients, handlers, long polling and webhooks.

```python
import os

from zalobot import Bot, Dispatcher, F

dp = Dispatcher()


@dp.message(F.text)
def echo(ctx):
    ctx.reply_text(ctx.text)


dp.run_polling(Bot(os.environ["ZALO_BOT_TOKEN"]))
```

- All 11 Bot API methods, each with a typed result.
- `Bot` (blocking) and `AsyncBot` (asyncio) with the same methods.
- Handlers, filters, long polling and webhook helpers for any framework.
- `Text` builds styled messages with correct UTF-16 offsets, so Vietnamese accents and emoji line up.
- The token never leaks into errors or logs.
- `FakeZalo` for offline tests.

Start with [Getting started](getting-started.md).
