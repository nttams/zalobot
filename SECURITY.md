# Security

## Reporting a vulnerability

Please don't open a public issue for a security problem. Email ngothtam.me@gmail.com with:

- what the problem is and its impact,
- steps to reproduce it,
- the zalobot version.

You'll get an answer within a week. Fixes for confirmed issues are released as soon as they're ready, and the
reporter is credited if they want to be.

## Supported versions

The latest release gets security fixes.

## Good practice for bot owners

- Keep the bot token out of code and logs (use environment variables). zalobot never prints it, but your own code
  might.
- Use a long random `secret_token` for webhooks, and always check the `X-Bot-Api-Secret-Token` header (`WebhookHandler` does it).
