from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from zalobot import AsyncBot, Bot
from zalobot.testing import FakeZalo

TOKEN = "1234567890:fake-zalobot-token"


@pytest.fixture
def fake() -> FakeZalo:
    return FakeZalo(token=TOKEN)


def answering(payload: Any, status: int = 200) -> httpx.MockTransport:
    """A transport that answers every call with ``payload`` (a dict -> JSON, bytes -> raw body)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(payload, bytes):
            return httpx.Response(status, content=payload)
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


def raising(exc: Exception) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return httpx.MockTransport(handler)


def recording(calls: list[tuple[str, dict[str, Any]]], payload: Any) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, json.loads(request.content or b"{}")))
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


MakeBot = Callable[..., Bot]
MakeAsyncBot = Callable[..., AsyncBot]
