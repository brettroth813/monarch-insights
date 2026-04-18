"""Webhook endpoint for receiving fresh Monarch session tokens from a browser.

Why a webhook:

The Monarch login flow is behind a Cloudflare WAF that rejects non-browser clients
(confirmed via direct probes — even ``curl_cffi`` with Safari/Chrome TLS fingerprints
gets ``{"You": "Shall Not Pass"}``). The only reliable way a Python client on the Pi
gets a Monarch session token is to reuse one that was issued to the user's browser
after they solved Cloudflare's browser challenge.

This module registers an HA webhook (``/api/webhook/<stable_id>``) that a small
browser-side script (a bookmarklet or Tampermonkey userscript) POSTs to with
``{"token": "..."}``. The webhook:

1. Validates the token against Monarch's ``me`` query (HTTP 401/404 → reject).
2. Updates the config entry's stored ``token`` + records the email in ``data``.
3. Triggers a coordinator reload so the new token takes effect immediately.

The webhook is deliberately stateless — we never persist anything the user didn't
ask us to. Every successful sync writes a single event-log row so operators can
audit "when did I last push a token" without digging through HA's logs.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from monarch_insights.client.api import MonarchClient
from monarch_insights.client.auth import MonarchAuth, Session
from monarch_insights.client.exceptions import MonarchAuthError, MonarchError

from .const import CONF_DEVICE_UUID, CONF_EMAIL, CONF_TOKEN, DOMAIN

if TYPE_CHECKING:  # pragma: no cover
    pass

_LOGGER = logging.getLogger(__name__)

WEBHOOK_ID_KEY = "webhook_id"


async def async_register_webhook(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Register (or re-register on reload) the token-push webhook for this entry.

    Returns the webhook id used by the URL so the config flow / options UI can
    display the full URL to the user. Idempotent — safe to call more than once.
    """
    webhook_id = entry.data.get(WEBHOOK_ID_KEY)
    if not webhook_id:
        # Generate a stable, opaque id. Using the entry_id keeps it unique per install
        # and avoids exposing the user email in the URL path.
        webhook_id = f"monarch_insights_{entry.entry_id}"
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, WEBHOOK_ID_KEY: webhook_id}
        )

    async def _handler(hass: HomeAssistant, wid: str, request: web.Request) -> web.Response:
        return await _receive_token(hass, entry, request)

    # ``async_register`` raises if the id is already registered — protect against
    # double-registration on integration reload.
    try:
        webhook.async_register(hass, DOMAIN, "Monarch Insights — token push", webhook_id, _handler)
    except ValueError:
        # Already registered (reload path). Unregister + re-register with the new handler
        # so the handler closure captures the current entry state.
        webhook.async_unregister(hass, webhook_id)
        webhook.async_register(hass, DOMAIN, "Monarch Insights — token push", webhook_id, _handler)

    _LOGGER.info("monarch_insights webhook ready at /api/webhook/%s", webhook_id)
    return webhook_id


async def async_unregister_webhook(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop the webhook when the entry is unloaded / removed."""
    webhook_id = entry.data.get(WEBHOOK_ID_KEY)
    if webhook_id:
        webhook.async_unregister(hass, webhook_id)


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------


async def _receive_token(
    hass: HomeAssistant, entry: ConfigEntry, request: web.Request
) -> web.Response:
    """Validate + persist a token pushed in by the browser-side helper."""
    # Accept either JSON body or a single-field form POST — makes curl + bookmarklet
    # parity trivial.
    try:
        if request.content_type == "application/json":
            body = await request.json()
        else:
            body = await request.post()
            body = dict(body)
    except Exception as exc:
        _LOGGER.info("webhook bad body: %s", exc)
        return web.json_response({"ok": False, "error": "bad_body"}, status=400)

    token = (body.get("token") or "").strip()
    if not token or len(token) < 16:
        return web.json_response({"ok": False, "error": "no_token"}, status=400)

    # Probe the token against Monarch's ``me`` query. If it's stale/invalid Monarch
    # responds 401 or 404, which our client turns into MonarchAuthError.
    device_uuid = entry.data.get(CONF_DEVICE_UUID) or "monarch-insights-webhook"
    auth = MonarchAuth(device_uuid=device_uuid)
    auth.session = Session(token=token, device_uuid=device_uuid)
    try:
        async with MonarchClient(auth) as client:
            me = await client.get_me()
    except MonarchAuthError:
        return web.json_response({"ok": False, "error": "invalid_token"}, status=401)
    except MonarchError as exc:
        _LOGGER.warning("webhook monarch probe failed: %s", exc)
        return web.json_response({"ok": False, "error": "monarch_probe_failed"}, status=502)

    email = (me or {}).get("email") or entry.data.get(CONF_EMAIL)
    new_data = {
        **entry.data,
        CONF_TOKEN: token,
        CONF_DEVICE_UUID: device_uuid,
        CONF_EMAIL: email,
    }
    hass.config_entries.async_update_entry(entry, data=new_data)

    # Reload the coordinator so the next refresh uses the new token immediately.
    await hass.config_entries.async_reload(entry.entry_id)

    _LOGGER.info("monarch_insights token refreshed via webhook for %s", email)
    return web.json_response({"ok": True, "email": email})
