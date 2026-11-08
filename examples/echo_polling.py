"""Echo bot with long polling (blocking). Run: ZALO_BOT_TOKEN=... python examples/echo_polling.py"""

import os

from zalobot import Bot, Context, Dispatcher, F

dp = Dispatcher()


@dp.command("start")
def start(ctx: Context) -> None:
    ctx.reply_text(f"Xin chào {ctx.message.from_user.display_name}! Send me anything and I'll send it back.")


@dp.message(F.text)
def echo(ctx: Context) -> None:
    ctx.reply_text(ctx.text or "")


@dp.message(F.photo)
def photo(ctx: Context) -> None:
    ctx.reply_text(f"Nice picture! Caption: {ctx.message.caption or '(none)'}")


if __name__ == "__main__":
    dp.run_polling(Bot(os.environ["ZALO_BOT_TOKEN"]))
