"""Coordinator polling, outage and cancellation regressions."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.aesl_smart_meter import coordinator as coordinator_module
from custom_components.aesl_smart_meter.api import (
    AESLAuthenticationError,
    AESLConnectionError,
)
from custom_components.aesl_smart_meter.coordinator import AESLDataCoordinator
from custom_components.aesl_smart_meter.sensor import DESCRIPTIONS, AESLSensor

ENDPOINTS = {
    "history": "async_get_log_history",
    "latest": "async_get_latest",
    "dashboard": "async_get_dashboard",
    "live": "async_get_live",
    "bill": "async_get_recent_bill",
    "mdi": "async_get_mdi",
}


@pytest_asyncio.fixture
async def hass(tmp_path):
    """Use Home Assistant's real coordinator runtime without external services."""
    instance = HomeAssistant(str(tmp_path))
    yield instance
    await instance.async_stop()


@pytest.fixture
def client():
    """Independent endpoint responses without contacting the portal."""
    return SimpleNamespace(
        **{
            method: AsyncMock(return_value={"source": source})
            for source, method in ENDPOINTS.items()
        }
    )


@pytest.fixture
def coordinator(hass, client):
    return AESLDataCoordinator(
        hass, client, {"login_id": "synthetic-consumer", "meter_id": 12, "phase": 1}
    )


@pytest.fixture
def clock(monkeypatch):
    """Control polling time independently of the host clock."""
    now = [datetime(2026, 1, 1, tzinfo=UTC)]

    class Clock:
        @staticmethod
        def now(_timezone):
            return now[0]

    monkeypatch.setattr(coordinator_module, "datetime", Clock)
    return now


@pytest.mark.asyncio
async def test_failed_slow_source_retries_independently(coordinator, client, clock):
    client.async_get_recent_bill.side_effect = AESLConnectionError("Temporary outage")

    first = await coordinator._async_update_data()

    assert "bill" not in first
    assert first["mdi"] == {"source": "mdi"}
    assert coordinator._last_slow_success == {"mdi": clock[0]}

    client.async_get_recent_bill.side_effect = None
    clock[0] += timedelta(minutes=15)
    recovered = await coordinator._async_update_data()

    assert recovered["bill"] == {"source": "bill"}
    assert client.async_get_recent_bill.await_count == 2
    assert client.async_get_mdi.await_count == 1

    await coordinator._async_update_data()
    assert client.async_get_recent_bill.await_count == 2
    assert client.async_get_mdi.await_count == 1


@pytest.mark.asyncio
async def test_successful_slow_sources_follow_twelve_hour_interval(
    coordinator, client, clock
):
    initial = await coordinator._async_update_data()
    clock[0] += timedelta(hours=11, minutes=59)

    cached = await coordinator._async_update_data()

    assert cached["bill"] == initial["bill"]
    assert client.async_get_recent_bill.await_count == 1
    assert client.async_get_mdi.await_count == 1

    clock[0] += timedelta(minutes=1)
    await coordinator._async_update_data()
    assert client.async_get_recent_bill.await_count == 2
    assert client.async_get_mdi.await_count == 2


@pytest.mark.asyncio
async def test_partial_outage_keeps_successful_sources(coordinator, client):
    await coordinator._async_update_data()
    client.async_get_latest.side_effect = AESLConnectionError("Reading unavailable")

    result = await coordinator._async_update_data()

    assert "latest" not in result
    assert result["history"] == {"source": "history"}
    assert result["dashboard"] == {"source": "dashboard"}
    assert result["bill"] == {"source": "bill"}


@pytest.mark.asyncio
async def test_latest_and_live_requests_include_consumer_context(coordinator, client):
    await coordinator._async_update_data()

    client.async_get_latest.assert_awaited_once_with("synthetic-consumer", 12, 1)
    client.async_get_live.assert_awaited_once_with("synthetic-consumer", 12, 1)


@pytest.mark.asyncio
async def test_live_outage_does_not_hide_summary_readings(coordinator, client):
    client.async_get_live.side_effect = AESLConnectionError("Live reading unavailable")

    result = await coordinator._async_update_data()

    assert "live" not in result
    assert result["latest"] == {"source": "latest"}
    assert result["history"] == {"source": "history"}


@pytest.mark.asyncio
async def test_failed_reading_sources_cannot_supply_stale_sensor_fallback(
    coordinator, client
):
    client.async_get_latest.return_value = {"table1": [{"kW": 100.0}]}
    client.async_get_live.return_value = {"meterData": [{"kw": 99.0}]}
    coordinator.data = await coordinator._async_update_data()
    description = next(item for item in DESCRIPTIONS if item.key == "active_power")
    sensor = AESLSensor(coordinator, "synthetic-consumer", description)
    assert sensor.native_value == 100.0

    client.async_get_latest.side_effect = AESLConnectionError(
        "Latest reading unavailable"
    )
    client.async_get_live.side_effect = AESLConnectionError("Live reading unavailable")
    coordinator.data = await coordinator._async_update_data()

    assert "latest" not in coordinator.data
    assert "live" not in coordinator.data
    assert sensor.native_value is None
    assert not sensor.available


@pytest.mark.asyncio
async def test_missing_meter_id_skips_meter_specific_requests(hass, client):
    coordinator = AESLDataCoordinator(hass, client, {"login_id": "synthetic-consumer"})

    result = await coordinator._async_update_data()

    assert set(result) == {"history", "latest", "bill"}
    client.async_get_live.assert_not_awaited()
    client.async_get_dashboard.assert_not_awaited()
    client.async_get_mdi.assert_not_awaited()


@pytest.mark.asyncio
async def test_total_outage_fails_refresh_without_marking_slow_success(
    coordinator, client
):
    for method in ENDPOINTS.values():
        getattr(client, method).side_effect = AESLConnectionError("Portal unavailable")

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert coordinator._last_slow_success == {}


@pytest.mark.asyncio
async def test_authentication_failure_requires_reauthentication(coordinator, client):
    client.async_get_latest.side_effect = AESLAuthenticationError("Session expired")

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()

    assert coordinator._cache == {}
    assert coordinator._last_slow_success == {}


@pytest.mark.asyncio
async def test_endpoints_run_concurrently(coordinator, client):
    started = set()
    all_started = asyncio.Event()
    release = asyncio.Event()

    async def response(source, *args):
        started.add(source)
        if len(started) == len(ENDPOINTS):
            all_started.set()
        await release.wait()
        return {"source": source}

    for source, method in ENDPOINTS.items():

        async def endpoint(*args, source=source):
            return await response(source, *args)

        setattr(client, method, endpoint)

    refresh = asyncio.create_task(coordinator._async_update_data())
    try:
        await asyncio.wait_for(all_started.wait(), timeout=1)
        assert started == set(ENDPOINTS)
    finally:
        release.set()
        result = await refresh

    assert set(result) == set(ENDPOINTS)


@pytest.mark.asyncio
async def test_cancelling_refresh_cancels_all_requests(coordinator, client):
    started = set()
    cancelled = set()
    all_started = asyncio.Event()

    for source, method in ENDPOINTS.items():

        async def endpoint(*args, source=source):
            started.add(source)
            if len(started) == len(ENDPOINTS):
                all_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.add(source)
                raise

        setattr(client, method, endpoint)

    refresh = asyncio.create_task(coordinator._async_update_data())
    try:
        await asyncio.wait_for(all_started.wait(), timeout=1)
    finally:
        refresh.cancel()
        with pytest.raises(asyncio.CancelledError):
            await refresh

    assert cancelled == set(ENDPOINTS)
    assert coordinator._cache == {}


@pytest.mark.asyncio
async def test_unexpected_programming_error_is_not_hidden(coordinator, client):
    client.async_get_latest.side_effect = ValueError("Unexpected response handler bug")

    with pytest.raises(ValueError):
        await coordinator._async_update_data()
