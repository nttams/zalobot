# Testing your bot

`zalobot.testing.FakeZalo` is an in-memory Bot API. It needs no network, no token and no Zalo account.

```python
from zalobot.testing import FakeZalo
from mybot import dp

def test_add_command():
    fake = FakeZalo()
    fake.push_text("/add 50k coffee")
    with fake.bot() as bot:
        for update in bot.get_updates():
            dp.feed(bot, update)
    assert fake.sent[0].text == "Added 50k for coffee"
```

| | |
|---|---|
| `push_text`, `push_photo`, `push_sticker`, `push_voice`, `push_unsupported` | a user writes to the bot (`chat_id=`, `user_id=`, `chat_type="GROUP"` ...) |
| `fake.bot()`, `fake.async_bot()` | bots wired to the fake |
| `fake.sent` | every send call: `.method`, `.chat_id`, `.text`, `.fields` |
| `fake.calls` | every call with its fields |
| `fake.fail(429, method="sendMessage", times=2)` | make calls fail |
| `fake.webhook_outcome = "webhook.http.403"` | what `test_webhook` / `set_webhook` report |
| `fake.deliver_webhook(handler)`, `await fake.adeliver_webhook(handler)` | POST queued updates to a webhook handler, with the secret header |

`getUpdates` hands out one queued update per call and answers 408 (no message) at once when the queue is empty. The
real API waits `timeout` seconds first. While a webhook is set, `getUpdates` fails with 400: the docs say the two
modes are exclusive but don't give an error code, so the fake uses 400.

To use any other httpx transport, pass `Bot(token, transport=...)` or `Bot(token, client=httpx.Client(...))`.
