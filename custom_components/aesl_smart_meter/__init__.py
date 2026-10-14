"""AESL Smart Meter integration (unofficial, read-only)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AESLClient
from .const import CONF_CLIENT_ID, CONF_TOKEN, DOMAIN
from .coordinator import AESLDataCoordinator

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a configured consumer account."""
    if not entry.data.get(CONF_TOKEN):
        raise ConfigEntryAuthFailed("Sign in to MahaVidyut to update this integration")
    client = AESLClient(
        async_get_clientsession(hass),
        token=entry.data[CONF_TOKEN],
        client_id=entry.data.get(CONF_CLIENT_ID),
    )
    coordinator = AESLDataCoordinator(hass, client, entry.data, config_entry=entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Keep consumer/entity IDs while requiring login for legacy entries."""
    if entry.version > 2:
        return False
    if entry.version == 1:
        hass.config_entries.async_update_entry(entry, version=2)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload sensors and release in-memory coordinator data."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded
