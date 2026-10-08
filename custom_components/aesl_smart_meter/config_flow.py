"""UI config flow for AESL Smart Meter."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AESLClient, AESLError
from .const import CONF_LOGIN_ID, CONF_METER_ID, CONF_PHASE, DOMAIN

_LOGGER = logging.getLogger(__name__)


class AESLSmartMeterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Collect your own portal consumer number and optional meter context."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            login_id = str(user_input[CONF_LOGIN_ID]).strip()
            try:
                client = AESLClient(async_get_clientsession(self.hass))
                # History request requires only the consumer number.
                await client.async_get_log_history(login_id)
            except AESLError as exc:
                _LOGGER.debug("AESL config validation failed: %s", exc)
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(login_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"AESL {login_id[-4:]}",
                    data={
                        CONF_LOGIN_ID: login_id,
                        CONF_METER_ID: int(user_input.get(CONF_METER_ID) or 0),
                        CONF_PHASE: int(user_input.get(CONF_PHASE) or 1),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOGIN_ID): str,
                    vol.Optional(CONF_METER_ID, default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
                    vol.Optional(CONF_PHASE, default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=3)),
                }
            ),
            errors=errors,
        )
