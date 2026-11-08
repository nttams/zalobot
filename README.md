# zalobot

A typed Python library for the [Zalo Bot Platform](https://bot.zaloplatforms.com/docs/) with blocking and asyncio
clients, handlers, long polling and webhooks.

- **The whole Bot API**: all 11 methods, including `sendVoice`, `testWebhook` and the webhook check `setWebhook`
  now returns.
- **Typed**: every answer is a dataclass, and the package ships `py.typed` (it passes `mypy --strict`).
- **Blocking or asyncio**: `Bot` and `AsyncBot` have the same methods.
- **Rich text that lines up**: `Text` builds Zalo's `text_styles`. Their offsets are counted in UTF-16 units, so
  Vietnamese accents and emoji land in the right place.
- **Handlers like you know them**: `@dp.command("start")` and `@dp.message(F.photo)`, plus filters, an error hook
  and duplicate-message protection.
- **Safe by default**: the bot token never shows up in errors, `repr()` or httpx's request logs. Webhook secrets are
  compared in constant time.
- **Testable offline**: `zalobot.testing.FakeZalo` is an in-memory Bot API you can point a bot at in your own
  tests.

## Install

```bash
uv add zalobot-sdk        # or: pip install zalobot-sdk
```

The package is `zalobot-sdk` on PyPI, and you import it as `zalobot`. Python 3.11 or newer. The only dependency is [httpx](https://www.python-httpx.org/).

## Quickstart

Create a bot in the Zalo app: open the official account **Zalo Bot Manager**, tap **Tạo bot**, and give it a name
starting with "Bot". Zalo then sends you the token in a message.

```python
import os

from zalobot import Bot, Dispatcher, F

dp = Dispatcher()


@dp.message(F.text)
def echo(ctx):
    ctx.reply_text(ctx.text)


dp.run_polling(Bot(os.environ["ZALO_BOT_TOKEN"]))
```

Message your bot in Zalo, and it answers with the same text.

## Commands, filters, replies

```python
from zalobot import Context, Dispatcher, F

dp = Dispatcher()

@dp.command("add")                       # "/add 50k coffee" (any case)
def add(ctx: Context) -> None:
    ctx.reply_text(f"Added: {ctx.args}")  # "50k coffee"

@dp.message(F.photo & F.private)
def photo(ctx: Context) -> None:
    ctx.reply_text(f"Got your photo: {ctx.message.photo_url}")

@dp.fallback
def other(ctx: Context) -> None:
    ctx.reply_sticker("bfe458bf64fa8da4d4eb")

@dp.error
def on_error(ctx: Context, exc: Exception) -> None:
    ctx.reply_text("Sorry, something went wrong.")
```

Filters: `F.text`, `F.photo`, `F.sticker`, `F.voice`, `F.unsupported`, `F.private`, `F.group`,
`F.command(...)`, `F.regex(...)`, `F.from_user(...)` and `F.chat(...)`. Combine them with `&`, `|` and `~`. The first
matching handler wins. A `Router` groups handlers, and `dp.include(router)` adds the group to the dispatcher.

Replies: `ctx.reply_text`, `ctx.reply_long` (splits text over 2,000 characters at line breaks), `ctx.reply_photo`,
`ctx.reply_sticker`, `ctx.reply_voice` and `ctx.typing()`.

## asyncio

```python
from zalobot import AsyncBot, AsyncContext, Dispatcher, F

dp = Dispatcher()

@dp.message(F.text)
async def echo(ctx: AsyncContext) -> None:
    await ctx.typing()
    await ctx.reply_text(ctx.text)

dp.run(AsyncBot(token))             # or: await dp.start_polling(bot)
```

With an `AsyncBot`, plain `def` handlers still work: they run in a worker thread, and their replies go through
the same bot.

## Polling or webhook

Zalo delivers messages in one of two ways, and you can't use both at once:

| | Long polling | Webhook |
|---|---|---|
| How | `dp.run_polling(bot)` | Zalo POSTs to your HTTPS URL |
| Good for | development, small bots, no public server | production (Zalo's advice) |
| Setup | nothing | `bot.set_webhook(url, secret)` once |

While a webhook is set, Zalo turns `getUpdates` off. `run_polling` checks for this and tells you to call
`bot.delete_webhook()`.

Webhook with FastAPI (see `examples/webhook_flask.py` for Flask):

```python
from fastapi import FastAPI, Request, Response
from zalobot import AsyncBot, AsyncWebhookHandler

handler = AsyncWebhookHandler(dp, AsyncBot(token), secret="a-long-random-secret")
app = FastAPI()

@app.post("/zalo/webhook")
async def webhook(request: Request) -> Response:
    status, body = await handler.handle(request.headers, await request.body())
    return Response(body, status_code=status, media_type="application/json")
```

The handler checks the `X-Bot-Api-Secret-Token` header (403 if it's wrong) and the body (400 if it isn't an
update), then runs your handlers. `bot.set_webhook()` and `bot.test_webhook()` return Zalo's check of your URL, such
as `outcome="webhook.http.403"` with a hint about what to fix.

## Rich text

```python
from zalobot import Color, Size, Text

msg = (Text().size(Size.LARGE, "Đơn hàng #1024").plain("\n")
       .bullets(["Cà phê sữa đá: 29,000đ", "Bánh mì: 25,000đ"])
       .bold("Tổng: ").plain("54,000đ ").color(Color.GREEN, "✅ đã thanh toán"))
bot.send_message(chat_id, msg)
```

You can also let Zalo parse the markup: `bot.send_message(chat_id, "**bold** {red}red{/red}", parse_mode="markdown")`
or `parse_mode="html"`.

## Errors and retries

Each documented error code has its own exception, all subclasses of `zalobot.ZaloError`:

| Code | Exception |
|---|---|
| 400 | `BadRequest` |
| 401 | `Unauthorized` (token expired or wrong) |
| 403 | `Forbidden` |
| 404 | `NotFound` |
| 408 | `TimedOut` |
| 410 | `InvalidChat` (no such chat for this bot; not in Zalo's table) |
| 429 | `QuotaExceeded` |
| network failure | `NetworkError` |

The real API answers errors with HTTP 200 and the code in the body; zalobot reads the body either way.

Retries are off by default. Turn them on with `Bot(token, retry=RetryPolicy(attempts=3))`: quota errors and
network errors are retried with doubling waits, while 401 never is. A send (`send_message`, `send_photo` ...) is
retried after a network error only if the request never left (connection refused or timed out): after a read
timeout Zalo may already have delivered it, and a retry would send it twice. Inputs that break the documented limits raise
`ValueError` before any request is sent: text over 2,000 characters (counted like Zalo's server, where most emoji
take 2), a secret shorter than 8, or a voice file that isn't `.aac`.

## Testing your bot

```python
from zalobot.testing import FakeZalo

def test_echo():
    fake = FakeZalo()
    fake.push_text("hello")                      # a user writes to the bot
    with fake.bot() as bot:
        for update in bot.get_updates():
            dp.feed(bot, update)
    assert fake.sent[0].text == "hello"          # what the bot sent back
```

`FakeZalo` answers with the shapes from the official docs. It can fail on demand (`fake.fail(429)`), and it can
deliver queued updates to a webhook handler (`fake.deliver_webhook(handler)`).

## Links

- Source and issues: https://github.com/nttams/zalobot
- Zalo Bot Platform docs: https://bot.zaloplatforms.com/docs/
- Changelog: [CHANGELOG.md](https://github.com/nttams/zalobot/blob/main/CHANGELOG.md)
- Contributing: [CONTRIBUTING.md](https://github.com/nttams/zalobot/blob/main/CONTRIBUTING.md)

zalobot is an independent project, not made or endorsed by Zalo or VNG. MIT licensed.
