"""Echo bot with asyncio. Run: ZALO_BOT_TOKEN=... python examples/echo_async.py"""

import os

from zalobot import AsyncBot, AsyncContext, Dispatcher, F

dp = Dispatcher()


@dp.message(F.text & F.private)
async def echo(ctx: AsyncContext) -> None:
    await ctx.typing()
    await ctx.reply_text(ctx.text or "")


if __name__ == "__main__":
    dp.run(AsyncBot(os.environ["ZALO_BOT_TOKEN"]))
