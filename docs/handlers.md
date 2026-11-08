# Handlers and filters

A handler is a function that takes one argument: a context with the update and reply helpers for its chat.

```python
from zalobot import Context, Dispatcher, F, Router

dp = Dispatcher()

@dp.command("add", "a")                   # "/add 50k coffee" or "/a ..." (any case)
def add(ctx: Context) -> None:
    amount, _, note = ctx.args.partition(" ")
    ctx.reply_text(f"Added {amount} for {note}")
```

## Which handler runs

The first handler whose filters all match gets the update. A dispatcher tries its own handlers in the order they
were added, then the routers added with `include()`, then its `fallback` (only the dispatcher has one).

```python
admin = Router("admin")

@admin.command("stats", filters=(F.from_user("6ede9afa66b88fe6d6a9"),))
def stats(ctx: Context) -> None: ...

dp.include(admin)

@dp.fallback
def unknown(ctx: Context) -> None:
    ctx.reply_text("Try /add 50k coffee")
```

## Filters

| Filter | Matches |
|---|---|
| `F.text`, `F.photo`, `F.sticker`, `F.voice` | the message kind |
| `F.unsupported` | a message Zalo withholds (protected accounts) |
| `F.private`, `F.group` | the chat type (bots in groups are in beta at Zalo) |
| `F.command("a", "b")` | `/a` or `/b`; `F.command()` = any command |
| `F.regex(r"\d+k")` | text, or a photo caption, matching the pattern |
| `F.from_user(id, ...)`, `F.chat(id, ...)` | given senders or chats |

Combine them: `F.text & F.private`, `F.photo | F.sticker`, `~F.command()`.

## The context

| | |
|---|---|
| `ctx.update`, `ctx.message` | the update and its message |
| `ctx.text`, `ctx.command`, `ctx.args` | the text, the command word, the text after it |
| `ctx.chat_id`, `ctx.user_id` | where it came from |
| `ctx.reply_text(text, parse_mode=None)` | send text or a `Text` |
| `ctx.reply_long(text)` | text over 2,000 characters, split at line breaks |
| `ctx.reply_photo(url, caption)`, `ctx.reply_sticker(id)`, `ctx.reply_voice(aac_url)` | media |
| `ctx.typing()` | show "typing..." |

## Errors in handlers

An exception in a handler never stops the bot. It goes to the router's `@router.error` hook, or the
dispatcher's. With no hook, it is logged on the `zalobot` logger. With an `AsyncBot`, an `async def` hook gets an
`AsyncContext` and a plain hook runs in a worker thread, as handlers do, so either kind can reply.

```python
@dp.error
def on_error(ctx: Context, exc: Exception) -> None:
    ctx.reply_text("Sorry, something went wrong.")
```

## Repeated messages

The dispatcher remembers the last 1,000 message ids (`Dispatcher(dedupe_size=...)`), so a message Zalo delivers
twice is handled once.

## Plain and async handlers

| Bot | `def` handler | `async def` handler |
|---|---|---|
| `Bot` | runs, gets `Context` | refused (TypeError) |
| `AsyncBot` | runs in a worker thread, gets `Context` | awaited, gets `AsyncContext` |
