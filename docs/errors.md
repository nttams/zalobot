# Errors and retries

Every failed call raises a subclass of `zalobot.ZaloError`, with `.code` (Zalo's `error_code`), `.description`
and `.method`:

| Code | Exception | Usually |
|---|---|---|
| 400 | `BadRequest` | invalid fields, wrong method |
| 401 | `Unauthorized` | the token expired or is wrong (retrying won't help) |
| 403 | `Forbidden` | Zalo's table says "internal server error" |
| 404 | `NotFound` | unknown method (Zalo's table says 400; the real API answers 404) |
| 408 | `TimedOut` | the request took too long (`get_updates` turns it into `[]`) |
| 410 | `InvalidChat` | no chat with that id for this bot (the real API's code; not in Zalo's table) |
| 429 | `QuotaExceeded` | over the API quota: slow down |
| none | `NetworkError` | DNS, TLS, connection or timeout before Zalo answered |

## Checks before sending

These raise `ValueError` without making a request:

- `text` and `caption` must be 1 to 2,000 characters, counted in UTF-16 units as Zalo's Java server counts them
  (most emoji take 2).
- `secret_token` must be 8 to 256 characters.
- The webhook URL must use `https://`.
- `photo` and `voice_url` must be `http(s)` URLs, and `voice_url` must end in `.aac`.

## Retries

Retries are off by default. Turn them on per bot:

```python
from zalobot import Bot, RetryPolicy

bot = Bot(token, retry=RetryPolicy(attempts=4, base_delay=1, max_delay=30))
```

`QuotaExceeded` and `NetworkError` are retried, waiting 1 s, then 2 s, then 4 s. Other errors are raised at once.
Set `retry_network=False` to retry quota errors only.

Sends are the exception: after a network error, `send_message`, `send_photo`, `send_sticker` and `send_voice` are
retried only when the request never left (`NetworkError.request_sent` is False: connection refused, connect or pool
timeout). After a read timeout or a dropped connection, Zalo may already have delivered the message, and a retry
would send it twice. Reads (`get_me`, `get_webhook_info` ...) are always safe to retry.

## The token stays secret

The token is part of every request URL. zalobot removes it from error messages and `repr(bot)`, and filters it out
of httpx's request log lines (which log URLs at INFO level). `bot.token` still gives it to you when you need it.
