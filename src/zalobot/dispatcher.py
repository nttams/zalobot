"""Routing updates to handlers, and long polling.

>>> from zalobot import Bot, Dispatcher
>>> dp = Dispatcher()
>>> @dp.command("start")
... def start(ctx):
...     ctx.reply_text("Xin chào!")
>>> dp.run_polling(Bot(TOKEN))     # doctest: +SKIP

Handlers take one argument, a context with the update and reply helpers. With a :class:`~zalobot.Bot` handlers are
plain functions. With an :class:`~zalobot.AsyncBot` they may be ``async def`` (they get an :class:`AsyncContext`)
or plain functions (run in a worker thread with a :class:`Context` whose replies go through the same AsyncBot).
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import threading
from collections import OrderedDict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from zalobot import errors
from zalobot._core import POLL_TIMEOUT
from zalobot.client import AsyncBot, Bot
from zalobot.filters import F, Filter
from zalobot.text import Text
from zalobot.types import ChatAction, Message, ParseMode, SentMessage, Update

__all__ = ["AsyncContext", "Context", "Dispatcher", "Router", "WebhookActiveError"]

log = logging.getLogger("zalobot")

HandlerT = TypeVar("HandlerT", bound=Callable[..., Any])


class WebhookActiveError(RuntimeError):
    """Polling refused: the bot has a webhook, and Zalo disables getUpdates while one is set."""


# --- contexts --------------------------------------------------------------------------------------------------


class _Sender(Protocol):
    def send_message(
        self, chat_id: str, text: str | Text, parse_mode: ParseMode | str | None = None
    ) -> SentMessage: ...
    def send_long_message(
        self, chat_id: str, text: str, parse_mode: ParseMode | str | None = None
    ) -> list[SentMessage]: ...
    def send_photo(self, chat_id: str, photo: str, caption: str | None = None) -> SentMessage: ...
    def send_sticker(self, chat_id: str, sticker: str) -> SentMessage: ...
    def send_voice(self, chat_id: str, voice_url: str) -> SentMessage: ...
    def send_chat_action(self, chat_id: str, action: ChatAction | str = ChatAction.TYPING) -> bool: ...


class _BaseContext:
    def __init__(self, update: Update) -> None:
        self.update = update

    @property
    def message(self) -> Message:
        if self.update.message is None:
            raise AttributeError("this update has no message")
        return self.update.message

    @property
    def chat_id(self) -> str:
        return self.message.chat.id

    @property
    def user_id(self) -> str:
        return self.message.from_user.id

    @property
    def text(self) -> str | None:
        return self.update.text

    @property
    def command(self) -> str | None:
        return self.update.command

    @property
    def args(self) -> str:
        return self.update.args


class Context(_BaseContext):
    """What a plain-function handler gets: the update plus blocking reply helpers for its chat."""

    def __init__(self, update: Update, bot: _Sender) -> None:
        super().__init__(update)
        self.bot = bot

    def reply_text(self, text: str | Text, parse_mode: ParseMode | str | None = None) -> SentMessage:
        return self.bot.send_message(self.chat_id, text, parse_mode)

    def reply_long(self, text: str, parse_mode: ParseMode | str | None = None) -> list[SentMessage]:
        return self.bot.send_long_message(self.chat_id, text, parse_mode)

    def reply_photo(self, photo: str, caption: str | None = None) -> SentMessage:
        return self.bot.send_photo(self.chat_id, photo, caption)

    def reply_sticker(self, sticker: str) -> SentMessage:
        return self.bot.send_sticker(self.chat_id, sticker)

    def reply_voice(self, voice_url: str) -> SentMessage:
        return self.bot.send_voice(self.chat_id, voice_url)

    def typing(self) -> bool:
        return self.bot.send_chat_action(self.chat_id, ChatAction.TYPING)


class AsyncContext(_BaseContext):
    """What an ``async def`` handler gets: the update plus awaitable reply helpers for its chat."""

    def __init__(self, update: Update, bot: AsyncBot) -> None:
        super().__init__(update)
        self.bot = bot

    async def reply_text(self, text: str | Text, parse_mode: ParseMode | str | None = None) -> SentMessage:
        return await self.bot.send_message(self.chat_id, text, parse_mode)

    async def reply_long(self, text: str, parse_mode: ParseMode | str | None = None) -> list[SentMessage]:
        return await self.bot.send_long_message(self.chat_id, text, parse_mode)

    async def reply_photo(self, photo: str, caption: str | None = None) -> SentMessage:
        return await self.bot.send_photo(self.chat_id, photo, caption)

    async def reply_sticker(self, sticker: str) -> SentMessage:
        return await self.bot.send_sticker(self.chat_id, sticker)

    async def reply_voice(self, voice_url: str) -> SentMessage:
        return await self.bot.send_voice(self.chat_id, voice_url)

    async def typing(self) -> bool:
        return await self.bot.send_chat_action(self.chat_id, ChatAction.TYPING)


class _ThreadBridge:
    """Blocking send methods for a plain handler running in a worker thread, run on the AsyncBot's loop."""

    def __init__(self, bot: AsyncBot, loop: asyncio.AbstractEventLoop) -> None:
        self._bot, self._loop = bot, loop

    def _run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            coro.close()
            raise RuntimeError(
                "a blocking reply was called on the event loop thread, where it would wait forever: "
                "use an async handler (or error hook) with AsyncBot, or call this from a worker thread"
            )
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def send_message(self, chat_id: str, text: str | Text, parse_mode: ParseMode | str | None = None) -> SentMessage:
        result: SentMessage = self._run(self._bot.send_message(chat_id, text, parse_mode))
        return result

    def send_long_message(
        self, chat_id: str, text: str, parse_mode: ParseMode | str | None = None
    ) -> list[SentMessage]:
        result: list[SentMessage] = self._run(self._bot.send_long_message(chat_id, text, parse_mode))
        return result

    def send_photo(self, chat_id: str, photo: str, caption: str | None = None) -> SentMessage:
        result: SentMessage = self._run(self._bot.send_photo(chat_id, photo, caption))
        return result

    def send_sticker(self, chat_id: str, sticker: str) -> SentMessage:
        result: SentMessage = self._run(self._bot.send_sticker(chat_id, sticker))
        return result

    def send_voice(self, chat_id: str, voice_url: str) -> SentMessage:
        result: SentMessage = self._run(self._bot.send_voice(chat_id, voice_url))
        return result

    def send_chat_action(self, chat_id: str, action: ChatAction | str = ChatAction.TYPING) -> bool:
        result: bool = self._run(self._bot.send_chat_action(chat_id, action))
        return result


# --- routing ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Route:
    filter: Filter
    handler: Callable[..., Any]


class Router:
    """A group of handlers. The first handler whose filters all match an update gets it."""

    def __init__(self, name: str = "") -> None:
        self.name = name
        self._routes: list[_Route] = []
        self._error_handler: Callable[..., Any] | None = None
        self._children: list[Router] = []

    def include(self, router: Router) -> Router:
        """Add a child router; it is tried after this router's own handlers."""
        if router is self:
            raise ValueError("a router cannot include itself")
        self._children.append(router)
        return router

    def add(self, handler: Callable[..., Any], *filters: Filter) -> None:
        combined = F.all
        for f in filters:
            combined = combined & f
        self._routes.append(_Route(combined, handler))

    def message(self, *filters: Filter) -> Callable[[HandlerT], HandlerT]:
        """``@router.message(F.text, F.private)``: handle updates matching all the filters (none = any update)."""

        def register(handler: HandlerT) -> HandlerT:
            self.add(handler, *filters)
            return handler

        return register

    def command(self, *names: str, filters: tuple[Filter, ...] = ()) -> Callable[[HandlerT], HandlerT]:
        """``@router.command("start", "help")``: ``/start`` or ``/start something`` (any case)."""
        if not names:
            raise ValueError("name at least one command")
        return self.message(F.command(*names), *filters)

    def error(self, handler: HandlerT) -> HandlerT:
        """``@router.error``: ``handler(ctx, exc)`` gets exceptions raised by this router's handlers."""
        self._error_handler = handler
        return handler

    def _find(self, update: Update) -> tuple[Callable[..., Any], Router] | None:
        for route in self._routes:
            if route.filter(update):
                return route.handler, self
        for child in self._children:
            found = child._find(update)
            if found:
                return found
        return None

    def _error_handler_for(self, router: Router) -> Callable[..., Any] | None:
        return router._error_handler or self._error_handler


class _Seen:
    """Message ids already handled: Zalo can hand the same message out again."""

    def __init__(self, size: int = 1000) -> None:
        self._ids: OrderedDict[str, None] = OrderedDict()
        self._size = size
        self._lock = threading.Lock()

    def first_time(self, update: Update) -> bool:
        key = update.message.message_id if update.message and update.message.message_id else None
        if key is None:
            return True
        with self._lock:
            if key in self._ids:
                return False
            self._ids[key] = None
            while len(self._ids) > self._size:
                self._ids.popitem(last=False)
            return True


class Dispatcher(Router):
    """The root router: feeds updates to handlers and runs long polling."""

    def __init__(self, name: str = "dispatcher", *, dedupe_size: int = 1000) -> None:
        super().__init__(name)
        self._fallback: Callable[..., Any] | None = None
        self._seen = _Seen(dedupe_size)
        self._stop = threading.Event()
        self._async_stop: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def fallback(self, handler: HandlerT) -> HandlerT:
        """``@dp.fallback``: gets updates no handler (in this dispatcher or its routers) matched."""
        self._fallback = handler
        return handler

    def _resolve(self, update: Update) -> tuple[Callable[..., Any], Router] | None:
        found = self._find(update)
        if found is None and self._fallback is not None:
            return self._fallback, self
        return found

    # --- feeding -----------------------------------------------------------------------------------------

    def feed(self, bot: Bot, update: Update) -> bool:
        """Handle one update with a blocking bot. -> whether a handler ran (False: no match, or a repeat)."""
        if not self._seen.first_time(update):
            return False
        found = self._resolve(update)
        if found is None:
            return False
        handler, router = found
        if inspect.iscoroutinefunction(handler):
            raise TypeError(f"{handler.__name__} is async: use AsyncBot to run async handlers")
        ctx = Context(update, bot)
        try:
            handler(ctx)
        except Exception as exc:
            self._handle_error_sync(router, ctx, exc)
        return True

    async def feed_async(self, bot: AsyncBot, update: Update) -> bool:
        """Handle one update with an AsyncBot. -> whether a handler ran."""
        if not self._seen.first_time(update):
            return False
        found = self._resolve(update)
        if found is None:
            return False
        handler, router = found
        try:
            await _call_handler(handler, update, bot)
        except Exception as exc:
            await self._handle_error_async(router, update, bot, exc)
        return True

    def _handle_error_sync(self, router: Router, ctx: Context, exc: Exception) -> None:
        on_error = self._error_handler_for(router)
        if on_error is None:
            log.exception("handler failed on message %s", _message_id(ctx.update), exc_info=exc)
            return
        if inspect.iscoroutinefunction(on_error):
            log.error("error hook %s is async: use AsyncBot to run async hooks", on_error.__name__, exc_info=exc)
            return
        try:
            on_error(ctx, exc)
        except Exception:
            log.exception("error handler failed")

    async def _handle_error_async(self, router: Router, update: Update, bot: AsyncBot, exc: Exception) -> None:
        """The hook gets the context its own kind needs: async hooks an AsyncContext, plain hooks a blocking
        Context in a worker thread (on the loop thread its replies would wait for the loop forever)."""
        on_error = self._error_handler_for(router)
        if on_error is None:
            log.exception("handler failed on message %s", _message_id(update), exc_info=exc)
            return
        try:
            await _call_handler(on_error, update, bot, exc)
        except Exception:
            log.exception("error handler failed")

    # --- polling -----------------------------------------------------------------------------------------

    def stop(self) -> None:
        """Ask the poll loop to finish. A blocking loop ends after its current long poll; an asyncio loop cancels
        it. ``getUpdates`` has no acknowledgement, so a message Zalo hands out at that moment can be lost.
        A stop asked for before the loop starts makes the next run return at once."""
        self._stop.set()
        loop, event = self._loop, self._async_stop
        if loop is not None and event is not None:
            with contextlib.suppress(RuntimeError):  # the loop closed meanwhile: nothing left to stop
                loop.call_soon_threadsafe(event.set)

    def run_polling(
        self,
        bot: Bot,
        *,
        timeout: int = POLL_TIMEOUT,
        backoff_start: float = 1.0,
        backoff_max: float = 60.0,
        check_webhook: bool = True,
    ) -> None:
        """Poll ``bot`` for updates and handle them until :meth:`stop` or Ctrl-C.

        Raises :class:`~zalobot.Unauthorized` for a dead token and :class:`WebhookActiveError` when a webhook is
        (or gets) set. Other errors (quota, network, server) wait, doubling up to ``backoff_max``, and go on."""
        if isinstance(bot, AsyncBot):
            raise TypeError("run_polling takes a Bot; use 'await dp.start_polling(async_bot)' for AsyncBot")
        try:
            if check_webhook:
                _refuse_webhook(bot.get_webhook_info().url)
            delay = backoff_start
            log.info("polling started")
            while not self._stop.is_set():
                try:
                    updates = bot.get_updates(timeout)
                except errors.Unauthorized:
                    raise
                except errors.ZaloError as e:
                    if isinstance(e, errors.BadRequest):
                        _refuse_webhook(_webhook_url(bot.get_webhook_info))
                    log.warning("getUpdates failed (%s); retrying in %.0fs", e, delay)
                    self._stop.wait(delay)
                    delay = min(backoff_max, delay * 2)
                    continue
                delay = backoff_start
                for update in updates:
                    self.feed(bot, update)
            log.info("polling stopped")
        except KeyboardInterrupt:
            log.info("polling stopped (Ctrl-C)")
        finally:
            self._stop.clear()

    async def start_polling(
        self,
        bot: AsyncBot,
        *,
        timeout: int = POLL_TIMEOUT,
        backoff_start: float = 1.0,
        backoff_max: float = 60.0,
        check_webhook: bool = True,
    ) -> None:
        """The asyncio twin of :meth:`run_polling`. :meth:`stop` (or cancelling the task) also cancels the
        current long poll."""
        if not isinstance(bot, AsyncBot):
            raise TypeError("start_polling takes an AsyncBot; use dp.run_polling(bot) for a Bot")
        stop = asyncio.Event()
        self._loop, self._async_stop = asyncio.get_running_loop(), stop
        if self._stop.is_set():
            stop.set()
        try:
            if check_webhook:
                _refuse_webhook((await bot.get_webhook_info()).url)
            delay = backoff_start
            log.info("polling started")
            while not stop.is_set():
                try:
                    updates = await _poll_or_stop(bot, timeout, stop)
                except errors.Unauthorized:
                    raise
                except errors.ZaloError as e:
                    if isinstance(e, errors.BadRequest):
                        _refuse_webhook(await _webhook_url_async(bot))
                    log.warning("getUpdates failed (%s); retrying in %.0fs", e, delay)
                    await _wait_or_stop(stop, delay)
                    delay = min(backoff_max, delay * 2)
                    continue
                if updates is None:
                    break
                delay = backoff_start
                for update in updates:
                    await self.feed_async(bot, update)
            log.info("polling stopped")
        finally:
            self._async_stop = None
            self._loop = None
            self._stop.clear()

    def run(self, bot: Bot | AsyncBot, **kwargs: Any) -> None:
        """Poll with either kind of bot from plain (non-async) code; Ctrl-C ends it quietly."""
        if isinstance(bot, AsyncBot):
            try:
                asyncio.run(self.start_polling(bot, **kwargs))
            except KeyboardInterrupt:
                log.info("polling stopped (Ctrl-C)")
        else:
            self.run_polling(bot, **kwargs)


async def _call_handler(handler: Callable[..., Any], update: Update, bot: AsyncBot, *extra: Any) -> None:
    """Run a handler or hook under an AsyncBot: ``async def`` on the loop, plain functions in a worker thread."""
    if inspect.iscoroutinefunction(handler):
        await handler(AsyncContext(update, bot), *extra)
    else:
        ctx = Context(update, _ThreadBridge(bot, asyncio.get_running_loop()))
        await asyncio.to_thread(handler, ctx, *extra)


async def _poll_or_stop(bot: AsyncBot, timeout: int, stop: asyncio.Event) -> list[Update] | None:
    """One long poll, or None when ``stop`` is set first. The poll is never left running: cancelling the caller
    cancels it too."""
    poll = asyncio.ensure_future(bot.get_updates(timeout))
    stopper = asyncio.ensure_future(stop.wait())
    try:
        done, _ = await asyncio.wait({poll, stopper}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (poll, stopper):
            if not task.done():
                task.cancel()
        await asyncio.gather(poll, stopper, return_exceptions=True)
    if poll in done:
        return poll.result()
    return None


def _webhook_url(get_info: Callable[[], Any]) -> str:
    """The webhook URL, re-checked after getUpdates failed with 400. Only a dead token stops polling here: any
    other error of the check itself is logged and polling backs off as usual."""
    try:
        return str(get_info().url)
    except errors.Unauthorized:
        raise
    except errors.ZaloError as e:
        log.warning("webhook check failed (%s)", e)
        return ""


async def _webhook_url_async(bot: AsyncBot) -> str:
    try:
        return (await bot.get_webhook_info()).url
    except errors.Unauthorized:
        raise
    except errors.ZaloError as e:
        log.warning("webhook check failed (%s)", e)
        return ""


def _refuse_webhook(url: str) -> None:
    if url:
        raise WebhookActiveError(
            f"this bot has a webhook ({url}), and Zalo turns getUpdates off while one is set: "
            "call bot.delete_webhook() first, or serve the webhook instead (zalobot.webhook)"
        )


async def _wait_or_stop(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


def _message_id(update: Update) -> str:
    return update.message.message_id if update.message else "-"
