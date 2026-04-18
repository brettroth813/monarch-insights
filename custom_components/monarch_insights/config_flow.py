"""Config flow for the Monarch Insights Home Assistant integration.

Offers two starting paths from the menu:

1. **Email + password** (default): collect creds, call ``MonarchAuth.login``,
   branch to an MFA step if Monarch demands one.
2. **Paste existing token**: for users whose Monarch account is Apple-SSO-only
   (no working password) or who'd rather reuse a browser session token. The
   token is validated by calling ``me`` against Monarch before the entry is
   created, so a bad paste fails fast with a clear error.

On either path, success stores ``token`` + ``device_uuid`` + ``email`` in the
config entry data. The coordinator reconstitutes :class:`MonarchAuth` from
there — we never touch the encrypted on-disk session file from HA.

A unique-id is set to the lower-cased email so "Add Integration" twice is
idempotent instead of doubling API load.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from monarch_insights.client.api import MonarchClient
from monarch_insights.client.auth import MonarchAuth, Session
from monarch_insights.client.exceptions import MonarchAuthError, MonarchMFARequired

from .const import (
    CONF_DEVICE_UUID,
    CONF_EMAIL,
    CONF_LOW_BALANCE_FLOOR,
    CONF_MFA_CODE,
    CONF_MFA_METHOD,
    CONF_PASSWORD,
    CONF_PRIMARY_CHECKING_ID,
    CONF_REFRESH_INTERVAL_MIN,
    CONF_TOKEN,
    DEFAULT_LOW_BALANCE_FLOOR,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


STEP_LOGIN_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_MFA_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MFA_METHOD, default="totp"): vol.In(["totp", "email_otp"]),
        vol.Required(CONF_MFA_CODE): str,
    }
)

STEP_TOKEN_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TOKEN): str,
    }
)


class MonarchInsightsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Interactive config flow with MFA + token-override branches."""

    VERSION = 1

    def __init__(self) -> None:
        self._email: str | None = None
        self._password: str | None = None
        # Shared across user → MFA transition so both login posts use the same
        # device UUID (Monarch challenges new-device logins, so consistency matters).
        self._auth: MonarchAuth | None = None

    async def async_step_user(self, user_input: dict | None = None):
        """Entry point: offer the two auth paths as a menu."""
        return self.async_show_menu(
            step_id="user",
            menu_options={
                "login": "Sign in with email + password",
                "token": "Paste an existing Monarch session token (advanced)",
            },
        )

    # ------------------------------------------------------------------ login path

    async def async_step_login(self, user_input: dict | None = None):
        """Collect email + password and try the first login leg."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip().lower()
            self._password = user_input[CONF_PASSWORD]

            await self.async_set_unique_id(self._email)
            self._abort_if_unique_id_configured()

            # ``save=False`` keeps the token off disk; we persist into ``entry.data``.
            self._auth = MonarchAuth()
            try:
                session = await self._auth.login(self._email, self._password, save=False)
            except MonarchMFARequired:
                return await self.async_step_mfa()
            except MonarchAuthError as exc:
                _LOGGER.info("monarch_insights auth failed: %s", exc)
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001 — HA config flow convention
                _LOGGER.exception("monarch_insights unexpected auth error")
                errors["base"] = "unknown"
            else:
                return self._finalize(session.token, session.device_uuid)

        return self.async_show_form(
            step_id="login", data_schema=STEP_LOGIN_DATA_SCHEMA, errors=errors
        )

    async def async_step_mfa(self, user_input: dict | None = None):
        """Collect the MFA code and finish login."""
        errors: dict[str, str] = {}
        if user_input is not None:
            assert self._auth is not None and self._email and self._password
            try:
                session = await self._auth.submit_mfa(
                    self._email,
                    self._password,
                    user_input[CONF_MFA_CODE],
                    method=user_input[CONF_MFA_METHOD],
                    save=False,
                )
            except MonarchAuthError as exc:
                _LOGGER.info("monarch_insights MFA failed: %s", exc)
                errors["base"] = "invalid_mfa"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("monarch_insights unexpected MFA error")
                errors["base"] = "unknown"
            else:
                return self._finalize(session.token, session.device_uuid)

        return self.async_show_form(
            step_id="mfa", data_schema=STEP_MFA_DATA_SCHEMA, errors=errors
        )

    # ------------------------------------------------------------------ token path

    async def async_step_token(self, user_input: dict | None = None):
        """Accept a raw Monarch session token (from browser DevTools) and verify it.

        Validation calls ``me`` — if Monarch returns 200 with our user object we
        persist the token; any other response fails with ``invalid_auth``.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            if not token:
                errors["base"] = "invalid_auth"
            else:
                device_uuid = str(uuid.uuid4())
                auth = MonarchAuth(device_uuid=device_uuid)
                auth.session = Session(token=token, device_uuid=device_uuid)
                try:
                    async with MonarchClient(auth) as client:
                        me = await client.get_me()
                except MonarchAuthError as exc:
                    _LOGGER.info("monarch_insights token rejected: %s", exc)
                    errors["base"] = "invalid_auth"
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("monarch_insights token probe failed")
                    errors["base"] = "unknown"
                else:
                    email = (me or {}).get("email")
                    if not email:
                        errors["base"] = "invalid_auth"
                    else:
                        self._email = email.strip().lower()
                        await self.async_set_unique_id(self._email)
                        self._abort_if_unique_id_configured()
                        return self._finalize(token, device_uuid)

        return self.async_show_form(
            step_id="token",
            data_schema=STEP_TOKEN_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "instructions": (
                    "Open app.monarch.com in a browser, DevTools → Network → any "
                    "graphql request → copy the value after 'Authorization: Token '."
                ),
            },
        )

    # ------------------------------------------------------------------ helpers

    def _finalize(self, token: str, device_uuid: str) -> dict[str, Any]:
        """Persist token + device UUID onto the config entry and finish the flow."""
        assert self._email
        return self.async_create_entry(
            title=self._email,
            data={
                CONF_EMAIL: self._email,
                CONF_TOKEN: token,
                CONF_DEVICE_UUID: device_uuid,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return MonarchInsightsOptionsFlow(config_entry)


class MonarchInsightsOptionsFlow(config_entries.OptionsFlow):
    """Lets the user tune polling interval + alert floors after install."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input: dict | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        opts = self.entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_REFRESH_INTERVAL_MIN,
                        default=opts.get(CONF_REFRESH_INTERVAL_MIN, DEFAULT_REFRESH_INTERVAL),
                    ): int,
                    vol.Optional(
                        CONF_LOW_BALANCE_FLOOR,
                        default=opts.get(CONF_LOW_BALANCE_FLOOR, DEFAULT_LOW_BALANCE_FLOOR),
                    ): int,
                    vol.Optional(
                        CONF_PRIMARY_CHECKING_ID,
                        default=opts.get(CONF_PRIMARY_CHECKING_ID, ""),
                    ): str,
                }
            ),
        )
