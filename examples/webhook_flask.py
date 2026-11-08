"""Webhook bot on Flask (blocking).

    pip install zalobot-sdk flask
    ZALO_BOT_TOKEN=... ZALO_WEBHOOK_SECRET=... flask --app examples.webhook_flask run

Register the public HTTPS URL once: bot.set_webhook("https://your.domain/zalo/webhook", secret).
"""

import os

from flask import Flask, Response, request

from zalobot import Bot, Context, Dispatcher, F, WebhookHandler

dp = Dispatcher()


@dp.message(F.text)
def echo(ctx: Context) -> None:
    ctx.reply_text(f"You said: {ctx.text}")


def create_app(bot: Bot, secret: str) -> Flask:
    handler = WebhookHandler(dp, bot, secret)
    flask_app = Flask(__name__)

    @flask_app.post("/zalo/webhook")
    def webhook() -> Response:
        status, body = handler.handle(request.headers, request.get_data())
        return Response(body, status=status, mimetype="application/json")

    return flask_app


if os.environ.get("ZALO_BOT_TOKEN"):
    app = create_app(Bot(os.environ["ZALO_BOT_TOKEN"]), os.environ["ZALO_WEBHOOK_SECRET"])
