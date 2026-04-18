"""Config flow for the Monarch Insights Home Assistant integration.

Three-step flow:

1. ``async_step_user`` collects email + password. We call ``MonarchAuth.login`` which
   either (a) succeeds, (b) raises :class:`MonarchMFARequired` — branch to MFA step,
   or (c) raises :class:`MonarchAuthError` — show the invalid-auth error.
2. ``async_step_mfa`` collects the TOTP / email-OTP code and finishes login.
3. On success we store the **token** inside the entry's ``data`` dict (not the password)
   so the coordinator can recreate the :class:`MonarchAuth` object without prompting
   again. We deliberately avoid writing the on-disk session file from inside HA because
   HA containers on HAOS have a different ``$HOME`` than the user's shell; keeping the
   token in HA storage is both simpler and survives container restarts cleanly.

A unique-id is set to the lower-cased email so "Add Integration" twice doesn't create
two entries polling the same Monarch account.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from monarch_insights.client.auth import MonarchAuth
from monarch_insights.client.exceptions import MonarchAuthError, MonarchMFARequired

from .const import (
    CONF_EMAIL,
    CONF_LOW_BALANCE_FLOOR,
    CONF_MFA_CODE,
    CONF_MFA_METHOD,
    CONF_PASSWORD,
    CONF_PRIMARY_CHECKING_ID,
    CONF_REFRESH_INTERVAL_MIN,
    DEFAULT_LOW_BALANCE_FLOOR,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

CONF_TOKEN = "token"
CONF_DEVICE_UUID = "device_uuid"

STEP_USER_DATA_SCHEMA = vol.Schema(
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


class MonarchInsightsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Interactive config flow with MFA branching."""

    VERSION = 1

    def __init__(self) -> None:
        self._email: str | None = None
        self._password: str | None = None
        # ``MonarchAuth`` caches the device UUID; we reuse a single instance across the
        # user → MFA transition so both login posts share the same UUID (Monarch
        # challenges new-device logins, so consistency matters here).
        self._auth: MonarchAuth | None = None

    async def async_step_user(self, user_input: dict | None = None):
        """Collect email + password and try the first login leg."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip().lower()
            self._password = user_input[CONF_PASSWORD]

            # Guard against duplicate entries — one Monarch account per HA install.
            await self.async_set_unique_id(self._email)
            self._abort_if_unique_id_configured()

            # ``save=False`` keeps the token off disk during config-flow; we'll persist
            # it into ``entry.data`` on success.
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
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
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
