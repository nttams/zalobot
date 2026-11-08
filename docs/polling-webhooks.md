# Polling and webhooks

Zalo delivers new messages in one of two ways. The two are mutually exclusive: while a webhook is set, `getUpdates`
is turned off.

## Long polling

```python
dp.run_polling(bot)                         # Bot: blocks until dp.stop(), Ctrl-C or a dead token
await dp.start_polling(async_bot)           # AsyncBot
dp.run(bot_or_async_bot)                    # either, from plain code
```

- Each call to `getUpdates` waits up to `timeout` seconds (default 30) for a message.
- Quota, network and server errors wait and retry, doubling from `backoff_start` up to `backoff_max` (1 s to 60 s).
- A 401 (token expired or wrong) raises `Unauthorized` and stops.
- If a webhook gets set while polling runs, `getUpdates` starts failing. The loop then checks `get_webhook_info()`
  and raises `WebhookActiveError` instead of retrying forever.
- `dp.stop()` ends the loop. Under asyncio it also cancels the current long poll, and cancelling the
  `start_polling` task does the same. `getUpdates` has no acknowledgement, so a message Zalo hands out at that
  very moment can be lost.
- At start it checks `get_webhook_info()` and raises `WebhookActiveError` if a webhook is set. Pass
  `check_webhook=False` to skip the check.

Zalo recommends polling for development and webhooks for production, where they say you are less likely to miss
events.

## Webhooks

1. Run an HTTPS endpoint that Zalo can reach from the internet. Zalo refuses `localhost`, private IPs and redirects.
   For local development, use a tunnel such as ngrok or Cloudflare Tunnel.
2. Register it once with a secret of 8 to 256 characters:

    ```python
    info = bot.set_webhook("https://your.domain/zalo/webhook", "a-long-random-secret")
    print(info.verification.outcome, info.verification.hint)
    ```

3. In your endpoint, pass the headers and raw body to a handler and return what it gives back:

    ```python
    handler = WebhookHandler(dp, bot, secret="a-long-random-secret")        # AsyncWebhookHandler for asyncio
    status, body = handler.handle(request.headers, request_body_bytes)
    ```

The handler returns 403 when the `X-Bot-Api-Secret-Token` header is wrong or missing (compared in constant time),
400 when the body isn't an update, and 200 after running your handlers. Handler errors still return 200, so that
Zalo doesn't keep re-sending a message your code can't handle.

See `examples/webhook_fastapi.py` and `examples/webhook_flask.py`.

### Checking the webhook

`bot.test_webhook()` asks Zalo to call your URL right now:

| outcome | meaning |
|---|---|
| `webhook.ok` | your URL answered 2xx |
| `webhook.http.403` | your server or CDN refused it (WAF rules, IP allowlist, User-Agent `Java/...`) |
| `webhook.http.404` | nothing at that path, or the endpoint doesn't accept POST |
| `webhook.http.5xx` | your server failed |
| `webhook.http.other` | another status (Zalo doesn't follow redirects) |
| `webhook.err.tls` | certificate problem |
| `webhook.err.unreachable` | no answer (DNS, firewall, too slow, or a forbidden address) |

`bot.delete_webhook()` switches back to polling.

Messages that arrive while a webhook is set go to the webhook, not to `getUpdates`, and switching back to polling
doesn't hand them over. If your endpoint isn't answering when Zalo calls it, those messages may be lost. Check
with `bot.test_webhook()` before you rely on a webhook, and don't set a test webhook on a bot people are using.

With no webhook set, the real API answers `getWebhookInfo` with 404, which `get_webhook_info()` turns into
`url == ""`. `deleteWebhook` and `testWebhook` answer 400 in that case.
