# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/). Before 1.0 a minor version may change the API.

## [Unreleased]

## [0.1.0] - 2026-11-08

### Added

- `Bot` (blocking) and `AsyncBot` (asyncio) with every Zalo Bot API method: `get_me`, `get_updates`,
  `set_webhook`, `test_webhook`, `delete_webhook`, `get_webhook_info`, `send_message`, `send_photo`,
  `send_sticker`, `send_voice` and `send_chat_action`, plus `send_long_message`.
- A typed dataclass for every answer, keeping the raw JSON in `.raw`.
- An exception for each documented error code, plus `NetworkError`. The bot token is removed from errors,
  `repr()` and httpx log lines.
- Checks against the documented limits before sending, and an opt-in `RetryPolicy` for quota and network errors.
- `Text`, a builder for `text_styles` with UTF-16 offsets, and `split_text`.
- `Dispatcher` and `Router` with command and message handlers, filters `F` (combinable with `&`, `|`, `~`),
  fallback and error hooks, and duplicate-message protection.
- Long polling (`run_polling`, `start_polling`, `run`) with backoff, a clean stop, and a refusal to start while a
  webhook is set.
- Webhook helpers that work with any framework: `verify_secret`, `parse_update`, `WebhookHandler` and
  `AsyncWebhookHandler`.
- `zalobot.testing.FakeZalo`, an in-memory Bot API for tests. It answers like the real API where the real API
  differs from the docs.
- `InvalidChat` (410) and `BotInfo.display_name`, both seen from the real API but not in the docs.
