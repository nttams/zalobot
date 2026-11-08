"""zalobot: a typed Python client and bot framework for the Zalo Bot Platform.

Official API docs: https://bot.zaloplatforms.com/docs/
"""

from zalobot._core import RetryPolicy
from zalobot.client import AsyncBot, Bot
from zalobot.dispatcher import AsyncContext, Context, Dispatcher, Router, WebhookActiveError
from zalobot.errors import (
    BadRequest,
    Forbidden,
    InvalidChat,
    NetworkError,
    NotFound,
    QuotaExceeded,
    TimedOut,
    Unauthorized,
    ZaloError,
)
from zalobot.filters import F, Filter
from zalobot.text import Color, Size, Text, split_text
from zalobot.types import (
    BotInfo,
    Chat,
    ChatAction,
    ChatType,
    EventName,
    Message,
    ParseMode,
    SentMessage,
    Update,
    User,
    WebhookCheck,
    WebhookInfo,
)
from zalobot.webhook import AsyncWebhookHandler, WebhookHandler

__version__ = "0.1.0"

__all__ = [
    "AsyncBot",
    "AsyncContext",
    "AsyncWebhookHandler",
    "BadRequest",
    "Bot",
    "BotInfo",
    "Chat",
    "ChatAction",
    "ChatType",
    "Color",
    "Context",
    "Dispatcher",
    "EventName",
    "F",
    "Filter",
    "Forbidden",
    "InvalidChat",
    "Message",
    "NetworkError",
    "NotFound",
    "ParseMode",
    "QuotaExceeded",
    "RetryPolicy",
    "Router",
    "SentMessage",
    "Size",
    "Text",
    "TimedOut",
    "Unauthorized",
    "Update",
    "User",
    "WebhookActiveError",
    "WebhookCheck",
    "WebhookHandler",
    "WebhookInfo",
    "ZaloError",
    "__version__",
    "split_text",
]
