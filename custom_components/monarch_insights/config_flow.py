"""Config flow for Monarch Insights — collects email/password and handles MFA."""

from __future__ import annotations

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
    VERSION = 1

    def __init__(self) -> None:
        self._email: str | None = None
        self._password: str | None = None

    async def async_step_user(self, user_input: dict | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]
            auth = MonarchAuth()
            try:
                await auth.login(self._email, self._password)
            except MonarchMFARequired:
                return await self.async_step_mfa()
            except MonarchAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=self._email,
                    data={CONF_EMAIL: self._email},
                )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_mfa(self, user_input: dict | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            auth = MonarchAuth()
            try:
                await auth.submit_mfa(
                    self._email,
                    self._password,
                    user_input[CONF_MFA_CODE],
                    method=user_input[CONF_MFA_METHOD],
                )
            except MonarchAuthError:
                errors["base"] = "invalid_mfa"
            else:
                return self.async_create_entry(
                    title=self._email,
                    data={CONF_EMAIL: self._email},
                )
        return self.async_show_form(
            step_id="mfa", data_schema=STEP_MFA_DATA_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return MonarchInsightsOptionsFlow(config_entry)


class MonarchInsightsOptionsFlow(config_entries.OptionsFlow):
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
                    vol.Optional(CONF_PRIMARY_CHECKING_ID, default=opts.get(CONF_PRIMARY_CHECKING_ID, "")): str,
                }
            ),
        )
