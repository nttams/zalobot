# Getting started

## 1. Make a bot

In the Zalo app, open the official account **Zalo Bot Manager** and tap **Tạo bot**. Name the bot (the name must
start with "Bot") and confirm. Zalo then sends you the bot **token** in a message. Keep it secret: anyone with the
token controls the bot.

## 2. Install

```bash
uv add zalobot-sdk        # or: pip install zalobot-sdk
```

The package is `zalobot-sdk` on PyPI; in code it is `import zalobot`.

## 3. Check the token

```python
from zalobot import Bot

with Bot("YOUR_TOKEN") as bot:
    me = bot.get_me()
    print(me.id, me.account_name)
```

A wrong or expired token raises `zalobot.Unauthorized`.

## 4. Answer messages

```python
from zalobot import Bot, Context, Dispatcher, F

dp = Dispatcher()

@dp.command("start")
def start(ctx: Context) -> None:
    ctx.reply_text(f"Xin chào {ctx.message.from_user.display_name}!")

@dp.message(F.text)
def echo(ctx: Context) -> None:
    ctx.reply_text(ctx.text or "")

dp.run_polling(Bot("YOUR_TOKEN"))
```

Message your bot in Zalo. A bot can only answer people who wrote to it: there is no API for starting a
conversation.

## 5. Or with asyncio

```python
from zalobot import AsyncBot, AsyncContext, Dispatcher, F

dp = Dispatcher()

@dp.message(F.text)
async def echo(ctx: AsyncContext) -> None:
    await ctx.reply_text(ctx.text or "")

dp.run(AsyncBot("YOUR_TOKEN"))
```

Next: [handlers and filters](handlers.md), then [polling or webhooks](polling-webhooks.md).
