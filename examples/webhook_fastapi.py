"""Webhook bot on FastAPI (asyncio).

    pip install zalobot-sdk fastapi uvicorn
    ZALO_BOT_TOKEN=... ZALO_WEBHOOK_SECRET=... uvicorn examples.webhook_fastapi:app

Register the public HTTPS URL once: bot.set_webhook("https://your.domain/zalo/webhook", secret).
"""

import os

from fastapi import FastAPI, Request, Response

from zalobot import AsyncBot, AsyncContext, AsyncWebhookHandler, Dispatcher, F

dp = Dispatcher()


@dp.message(F.text)
async def echo(ctx: AsyncContext) -> None:
    await ctx.reply_text(f"You said: {ctx.text}")


def create_app(bot: AsyncBot, secret: str) -> FastAPI:
    handler = AsyncWebhookHandler(dp, bot, secret)
    api = FastAPI()

    @api.post("/zalo/webhook")
    async def webhook(request: Request) -> Response:
        status, body = await handler.handle(request.headers, await request.body())
        return Response(body, status_code=status, media_type="application/json")

    return api


if os.environ.get("ZALO_BOT_TOKEN"):
    app = create_app(AsyncBot(os.environ["ZALO_BOT_TOKEN"]), os.environ["ZALO_WEBHOOK_SECRET"])
