"""Send a styled order summary with Text (bold, colours, lists). Zalo counts style offsets in UTF-16 units;
Text does that for you, so Vietnamese accents and emoji line up.

Run: ZALO_BOT_TOKEN=... ZALO_CHAT_ID=... python examples/rich_text.py
(the chat must have written to your bot first)
"""

import os

from zalobot import Bot, Color, Size, Text


def order_summary(order_id: str, items: list[tuple[str, int]], paid: bool) -> Text:
    total = sum(price for _, price in items)
    text = Text().size(Size.LARGE, f"Đơn hàng #{order_id}").plain("\n")
    text.bullets(f"{name}: {price:,}đ" for name, price in items)
    text.bold("Tổng: ").plain(f"{total:,}đ ")
    return text.color(Color.GREEN, "✅ đã thanh toán") if paid else text.color(Color.RED, "⏳ chưa thanh toán")


if __name__ == "__main__":
    with Bot(os.environ["ZALO_BOT_TOKEN"]) as bot:
        summary = order_summary("1024", [("Cà phê sữa đá", 29000), ("Bánh mì", 25000)], paid=True)
        bot.send_message(os.environ["ZALO_CHAT_ID"], summary)
