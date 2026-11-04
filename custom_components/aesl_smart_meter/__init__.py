"""MahaVidyut integration (unofficial, read-only)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MahaVidyutClient
from .const import CONF_CLIENT_ID, CONF_LOGIN_ID, CONF_TOKEN, DOMAIN, NAME
from .coordinator import MahaVidyutDataCoordinator

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a configured consumer account."""
    if not entry.data.get(CONF_TOKEN):
        raise ConfigEntryAuthFailed("Sign in to MahaVidyut to update this integration")
    client = MahaVidyutClient(
        async_get_clientsession(hass),
        token=entry.data[CONF_TOKEN],
        client_id=entry.data.get(CONF_CLIENT_ID),
    )
    coordinator = MahaVidyutDataCoordinator(
        hass, client, entry.data, config_entry=entry
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Update the default entry name without changing identity or custom titles."""
    if entry.version > 2:
        return False
    updates = {"version": 2, "minor_version": 2}
    login_id = str(entry.data.get(CONF_LOGIN_ID, ""))
    if login_id and entry.title == f"AESL {login_id[-4:]}":
        updates["title"] = f"{NAME} {login_id[-4:]}"
    hass.config_entries.async_update_entry(entry, **updates)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload sensors and release in-memory coordinator data."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded
