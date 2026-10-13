"""Sign in to MahaVidyut and discover the consumer's meter context."""

from __future__ import annotations

import logging
from dataclasses import replace

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    AESLAccount,
    AESLAuthenticationError,
    AESLClient,
    AESLError,
    AESLProtocolError,
)
from .const import (
    CONF_CLIENT_ID,
    CONF_LOGIN_ID,
    CONF_METER_ID,
    CONF_PHASE,
    CONF_TOKEN,
    CONF_USE_OTP,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
CONF_OTP = "otp"


class AESLSmartMeterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Store the authenticated session, never the password or SMS code."""

    VERSION = 2

    def __init__(self):
        self._login_id = ""
        self._password = ""
        self._use_otp = False
        self._client: AESLClient | None = None
        self._account: AESLAccount | None = None
        self._reauth_entry = None

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            login_id = str(user_input[CONF_LOGIN_ID]).strip()
            if not login_id:
                errors[CONF_LOGIN_ID] = "invalid_consumer"
            elif not user_input[CONF_PASSWORD]:
                errors[CONF_PASSWORD] = "invalid_auth"
            elif (
                self._reauth_entry
                and login_id != self._reauth_entry.data[CONF_LOGIN_ID]
            ):
                errors[CONF_LOGIN_ID] = "wrong_consumer"
            else:
                await self.async_set_unique_id(login_id)
                if self._reauth_entry is None:
                    self._abort_if_unique_id_configured()
                self._login_id = login_id
                self._use_otp = bool(user_input.get(CONF_USE_OTP, False))
                self._client = AESLClient(async_get_clientsession(self.hass))
                try:
                    if self._use_otp:
                        await self._client.async_request_otp(
                            login_id, user_input[CONF_PASSWORD]
                        )
                        self._password = user_input[CONF_PASSWORD]
                        return await self.async_step_otp()
                    account = await self._client.async_login(
                        login_id, user_input[CONF_PASSWORD]
                    )
                except AESLAuthenticationError:
                    errors["base"] = "invalid_auth"
                except AESLProtocolError:
                    errors["base"] = "invalid_response"
                except AESLError as exc:
                    _LOGGER.debug("MahaVidyut sign-in failed: %s", exc)
                    errors["base"] = "cannot_connect"
                else:
                    return self._finish(account)

        default_id = self._login_id
        if self._reauth_entry:
            default_id = self._reauth_entry.data[CONF_LOGIN_ID]
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOGIN_ID, default=default_id): str,
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_USE_OTP, default=self._use_otp): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_otp(self, user_input=None):
        errors = {}
        if self._client is None or not self._password:
            return await self.async_step_user()
        if user_input is not None:
            try:
                account = await self._client.async_verify_otp(
                    self._login_id, self._password, str(user_input[CONF_OTP]).strip()
                )
            except AESLAuthenticationError:
                errors["base"] = "invalid_otp"
            except AESLProtocolError:
                errors["base"] = "invalid_response"
            except AESLError as exc:
                _LOGGER.debug("MahaVidyut SMS verification failed: %s", exc)
                errors["base"] = "cannot_connect"
            else:
                return self._finish(account)
        return self.async_show_form(
            step_id="otp",
            data_schema=vol.Schema({vol.Required(CONF_OTP): str}),
            errors=errors,
        )

    def _finish(self, account: AESLAccount):
        self._password = ""
        self._client = None
        existing = self._reauth_entry.data if self._reauth_entry else {}
        account = replace(
            account,
            meter_id=account.meter_id or int(existing.get(CONF_METER_ID, 0)),
            phase=account.phase or int(existing.get(CONF_PHASE, 0)),
        )
        if not account.meter_id or not account.phase:
            self._account = account
            return self._show_meter_form()
        return self._create_account_entry(account)

    def _show_meter_form(self):
        return self.async_show_form(
            step_id="meter",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_METER_ID, default=self._account.meter_id
                    ): vol.All(vol.Coerce(int), vol.Range(min=0)),
                    vol.Optional(CONF_PHASE, default=self._account.phase or 1): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=3)
                    ),
                }
            ),
        )

    async def async_step_meter(self, user_input=None):
        if self._account is None:
            return await self.async_step_user()
        if user_input is not None:
            account = replace(
                self._account,
                meter_id=int(user_input.get(CONF_METER_ID, self._account.meter_id)),
                phase=int(user_input.get(CONF_PHASE, self._account.phase or 1)),
            )
            return self._create_account_entry(account)
        return self._show_meter_form()

    def _create_account_entry(self, account: AESLAccount):
        self._account = None
        data = {
            CONF_LOGIN_ID: account.login_id,
            CONF_TOKEN: account.token,
            CONF_CLIENT_ID: account.client_id,
            CONF_METER_ID: account.meter_id,
            CONF_PHASE: account.phase,
            CONF_USE_OTP: self._use_otp,
        }
        if self._reauth_entry:
            return self.async_update_reload_and_abort(
                self._reauth_entry, data_updates=data
            )
        return self.async_create_entry(title=f"AESL {account.login_id[-4:]}", data=data)

    async def async_step_reauth(self, entry_data):
        self._reauth_entry = self._get_reauth_entry()
        self._use_otp = bool(entry_data.get(CONF_USE_OTP, False))
        return await self.async_step_user()
