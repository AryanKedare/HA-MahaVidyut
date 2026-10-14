"""Entry migration and lifecycle regressions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components import aesl_smart_meter as integration


@pytest.fixture
def hass():
    return SimpleNamespace(
        data={},
        config_entries=SimpleNamespace(
            async_update_entry=MagicMock(),
            async_forward_entry_setups=AsyncMock(),
            async_unload_platforms=AsyncMock(return_value=True),
        ),
    )


@pytest.mark.asyncio
async def test_legacy_migration_keeps_identity_and_requires_login(hass):
    data = {"login_id": "test-ca", "meter_id": 42, "phase": 3}
    entry = SimpleNamespace(version=1, data=data, entry_id="entry")
    assert await integration.async_migrate_entry(hass, entry)
    hass.config_entries.async_update_entry.assert_called_once_with(entry, version=2)
    assert entry.data == data
    with pytest.raises(ConfigEntryAuthFailed):
        await integration.async_setup_entry(hass, entry)


@pytest.mark.asyncio
async def test_setup_session_coordinator_and_unload(hass, monkeypatch):
    entry = SimpleNamespace(
        data={"access_token": "token", "client_id": "client"}, entry_id="entry"
    )
    session = object()
    monkeypatch.setattr(
        integration, "async_get_clientsession", MagicMock(return_value=session)
    )
    api = MagicMock()
    monkeypatch.setattr(integration, "AESLClient", api)
    coordinator = SimpleNamespace(async_config_entry_first_refresh=AsyncMock())
    factory = MagicMock(return_value=coordinator)
    monkeypatch.setattr(integration, "AESLDataCoordinator", factory)
    assert await integration.async_setup_entry(hass, entry)
    api.assert_called_once_with(session, token="token", client_id="client")
    factory.assert_called_once_with(
        hass, api.return_value, entry.data, config_entry=entry
    )
    coordinator.async_config_entry_first_refresh.assert_awaited_once()
    assert hass.data["aesl_smart_meter"]["entry"] is coordinator
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, ["sensor"]
    )
    assert await integration.async_unload_entry(hass, entry)
    assert not hass.data["aesl_smart_meter"]


@pytest.mark.asyncio
async def test_future_entry_versions_are_not_downgraded(hass):
    assert not await integration.async_migrate_entry(hass, SimpleNamespace(version=3))
    hass.config_entries.async_update_entry.assert_not_called()
