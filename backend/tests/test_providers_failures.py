"""Unit tests for core/providers.py failure paths, network errors, retries,
and provider integrations."""
import json
import urllib.error as urllib_error
import urllib.request
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings

from core import providers
from core.models import Company, LLMConfig

pytestmark = pytest.mark.django_db


class _FakeStreamResponse:
    def __init__(self, lines):
        self._lines = lines

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_open_json_helper():
    calls = []

    def mock_urlopen(req, timeout=30.0):
        calls.append(req)
        resp = MagicMock()
        resp.read.return_value = b'{"status": "ok"}'
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        return resp

    with patch("core.providers._NO_REDIRECT_OPENER.open", side_effect=mock_urlopen):
        res = providers._json("http://test.api/ping", {"test": 1})
        assert res == {"status": "ok"}
        assert len(calls) == 1


def test_gemini_embed_empty_and_error():
    p = providers.GeminiProvider(api_key="gem-test", chat_model="gemini-2.5-flash")
    assert p.embed([]) is None

    with patch.object(providers, "_json", side_effect=Exception("API down")):
        res = p.embed(["hello world"])
        assert res is None  # Degrades gracefully when embedding fails


def test_gemini_stream_chat():
    p = providers.GeminiProvider(api_key="gem-test", chat_model="gemini-2.5-flash")
    sse_data = [
        b'data: {"candidates": [{"content": {"parts": [{"text": "Hello "}]}}]}\n',
        b'data: {"candidates": [{"content": {"parts": [{"text": "from Gemini!"}]}}]}\n',
    ]

    with patch("core.providers._NO_REDIRECT_OPENER.open", return_value=_FakeStreamResponse(sse_data)):
        tokens = list(p.stream_chat([{"role": "user", "content": "Hi"}]))
        assert "".join(tokens) == "Hello from Gemini!"


def test_anthropic_stream_chat():
    p = providers.AnthropicProvider(api_key="sk-ant-test", chat_model="claude-3-5-haiku-latest")
    sse_data = [
        b'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello "}}\n',
        b'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "from Claude!"}}\n',
    ]

    with patch("core.providers._NO_REDIRECT_OPENER.open", return_value=_FakeStreamResponse(sse_data)):
        tokens = list(p.stream_chat([{"role": "user", "content": "Hi"}]))
        assert "".join(tokens) == "Hello from Claude!"


def test_selfhosted_provider_attributes():
    p = providers.SelfHostedProvider(base_url="http://remote.llm:8000", chat_model="qwen2.5:7b", embed_model="nomic-embed-text")
    assert p.base == "http://remote.llm:8000"
    assert p.chat_model == "qwen2.5:7b"
    assert p.embed_model == "nomic-embed-text"


def test_get_chat_provider_selection():
    company = Company.objects.create(name="Prov Co", slug="prov-co")

    # Company with custom Gemini key
    LLMConfig.objects.create(company=company, provider="gemini", api_key="gem-key-123")
    prov = providers.get_chat_provider(company=company)
    assert isinstance(prov, providers.GeminiProvider)

    # Company with custom Anthropic key
    LLMConfig.objects.filter(company=company).update(provider="anthropic", api_key="ant-key-123")
    prov = providers.get_chat_provider(company=company)
    assert isinstance(prov, providers.AnthropicProvider)

    # Fake provider for test isolation
    LLMConfig.objects.filter(company=company).update(provider="fake", api_key="")
    prov = providers.get_chat_provider(company=company)
    assert isinstance(prov, providers.FakeProvider)
