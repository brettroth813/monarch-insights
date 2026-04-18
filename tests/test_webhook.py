"""Unit tests for the Monarch Insights token-push webhook handler.

We don't spin up Home Assistant — instead we test the handler's core validation
flow directly by mocking the ``MonarchClient`` it uses to probe ``me``. That
isolates the request parsing + response shape from the HA plumbing, which is
itself covered by the test_hacs_layout + config_flow tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Make the HACS-vendored library importable the same way the HA integration does.
VENDORED = Path(__file__).resolve().parent.parent / "custom_components" / "monarch_insights" / "_vendored"
if VENDORED.is_dir() and str(VENDORED) not in sys.path:
    sys.path.insert(0, str(VENDORED))


# Minimal stubs so the webhook module imports without a real HA installation.
class _StubWebhook:
    registered: dict = {}

    @classmethod
    def async_register(cls, hass, domain, name, webhook_id, handler):
        if webhook_id in cls.registered:
            raise ValueError("already registered")
        cls.registered[webhook_id] = handler

    @classmethod
    def async_unregister(cls, hass, webhook_id):
        cls.registered.pop(webhook_id, None)


# Install stubs before importing the module under test.
sys.modules.setdefault("homeassistant", MagicMock())
sys.modules.setdefault("homeassistant.components", MagicMock())
sys.modules.setdefault("homeassistant.components.webhook", _StubWebhook)
sys.modules.setdefault("homeassistant.config_entries", MagicMock())
sys.modules.setdefault("homeassistant.core", MagicMock())

from custom_components.monarch_insights import webhook as webhook_module  # noqa: E402


class _FakeRequest:
    """Minimal aiohttp Request shim that satisfies the handler's needs."""

    def __init__(self, body: dict | None = None, content_type: str = "application/json") -> None:
        self._body = body or {}
        self.content_type = content_type

    async def json(self):
        return self._body

    async def post(self):
        return self._body


class _FakeEntry:
    def __init__(self, entry_id: str = "entry1", data: dict | None = None):
        self.entry_id = entry_id
        self.data = dict(data or {})


class _FakeConfigEntries:
    def __init__(self):
        self.updated_with: dict | None = None
        self.reloaded: str | None = None

    def async_update_entry(self, entry, data):
        entry.data = dict(data)
        self.updated_with = entry.data

    async def async_reload(self, entry_id):
        self.reloaded = entry_id


class _FakeHass:
    def __init__(self):
        self.config_entries = _FakeConfigEntries()


@pytest.fixture
def hass():
    return _FakeHass()


@pytest.fixture
def entry():
    return _FakeEntry()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_accepts_valid_token(hass, entry):
    request = _FakeRequest({"token": "a" * 40})
    fake_client = AsyncMock()
    fake_client.get_me = AsyncMock(return_value={"email": "ok@example.com", "name": "Ok"})
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    with patch.object(webhook_module, "MonarchClient", return_value=fake_client):
        resp = await webhook_module._receive_token(hass, entry, request)
    assert resp.status == 200
    payload = json.loads(resp.body)
    assert payload["ok"] is True
    assert payload["email"] == "ok@example.com"
    assert entry.data["token"] == "a" * 40
    assert entry.data["email"] == "ok@example.com"
    assert hass.config_entries.reloaded == entry.entry_id


@pytest.mark.asyncio
async def test_webhook_rejects_missing_token(hass, entry):
    resp = await webhook_module._receive_token(hass, entry, _FakeRequest({}))
    assert resp.status == 400
    assert json.loads(resp.body)["error"] == "no_token"


@pytest.mark.asyncio
async def test_webhook_rejects_short_token(hass, entry):
    resp = await webhook_module._receive_token(hass, entry, _FakeRequest({"token": "short"}))
    assert resp.status == 400
    assert json.loads(resp.body)["error"] == "no_token"


@pytest.mark.asyncio
async def test_webhook_rejects_bad_body(hass, entry):
    class _Bad:
        content_type = "application/json"

        async def json(self):
            raise ValueError("bad")

    resp = await webhook_module._receive_token(hass, entry, _Bad())
    assert resp.status == 400
    assert json.loads(resp.body)["error"] == "bad_body"


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_token_per_monarch(hass, entry):
    from monarch_insights.client.exceptions import MonarchAuthError

    request = _FakeRequest({"token": "z" * 40})
    fake_client = AsyncMock()
    fake_client.get_me = AsyncMock(side_effect=MonarchAuthError("401"))
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    with patch.object(webhook_module, "MonarchClient", return_value=fake_client):
        resp = await webhook_module._receive_token(hass, entry, request)
    assert resp.status == 401
    assert json.loads(resp.body)["error"] == "invalid_token"
    assert entry.data.get("token") != "z" * 40   # original data untouched


@pytest.mark.asyncio
async def test_webhook_monarch_server_error_returns_502(hass, entry):
    from monarch_insights.client.exceptions import MonarchError

    request = _FakeRequest({"token": "q" * 40})
    fake_client = AsyncMock()
    fake_client.get_me = AsyncMock(side_effect=MonarchError("boom"))
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    with patch.object(webhook_module, "MonarchClient", return_value=fake_client):
        resp = await webhook_module._receive_token(hass, entry, request)
    assert resp.status == 502
