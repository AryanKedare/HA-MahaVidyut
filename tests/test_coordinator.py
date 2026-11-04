"""Coordinator polling, outage and cancellation regressions."""

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.aesl_smart_meter import (
    api as api_module,
)
from custom_components.aesl_smart_meter import (
    const,
)
from custom_components.aesl_smart_meter import (
    coordinator as coordinator_module,
)
from custom_components.aesl_smart_meter.api import (
    MahaVidyutAccount,
    MahaVidyutAuthenticationError,
    MahaVidyutConnectionError,
    MahaVidyutProtocolError,
)
from custom_components.aesl_smart_meter.coordinator import MahaVidyutDataCoordinator
from custom_components.aesl_smart_meter.sensor import DESCRIPTIONS, MahaVidyutSensor

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
    return MahaVidyutDataCoordinator(
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
    client.async_get_recent_bill.side_effect = MahaVidyutConnectionError(
        "Temporary outage"
    )

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
    client.async_get_latest.side_effect = MahaVidyutConnectionError(
        "Reading unavailable"
    )

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
    client.async_get_live.side_effect = MahaVidyutConnectionError(
        "Live reading unavailable"
    )

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
    sensor = MahaVidyutSensor(coordinator, "synthetic-consumer", description)
    assert sensor.native_value == 100.0

    client.async_get_latest.side_effect = MahaVidyutConnectionError(
        "Latest reading unavailable"
    )
    client.async_get_live.side_effect = MahaVidyutConnectionError(
        "Live reading unavailable"
    )
    coordinator.data = await coordinator._async_update_data()

    assert "latest" not in coordinator.data
    assert "live" not in coordinator.data
    assert sensor.native_value is None
    assert not sensor.available


@pytest.mark.asyncio
async def test_missing_meter_id_skips_meter_specific_requests(hass, client):
    coordinator = MahaVidyutDataCoordinator(
        hass, client, {"login_id": "synthetic-consumer"}
    )

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
        getattr(client, method).side_effect = MahaVidyutConnectionError(
            "Portal unavailable"
        )

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert coordinator._last_slow_success == {}


@pytest.mark.asyncio
async def test_authentication_failure_requires_reauthentication(coordinator, client):
    client.async_get_latest.side_effect = MahaVidyutAuthenticationError(
        "Session expired"
    )

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


@pytest.fixture
def automatic(hass, client):
    coordinator = MahaVidyutDataCoordinator(
        hass,
        client,
        {
            "login_id": "synthetic-consumer",
            "meter_id": 12,
            "phase": 1,
            "auto_reauthenticate": True,
            "password": "synthetic-password",
        },
    )
    client.async_login = AsyncMock(
        return_value=MahaVidyutAccount(
            "synthetic-consumer", "new-token", 99, 3, "new-client"
        )
    )
    client.set_account = MagicMock()
    return coordinator


@pytest.mark.asyncio
async def test_all_expired_endpoints_share_one_login_and_retry(
    automatic, client, caplog
):
    for source, method in ENDPOINTS.items():
        getattr(client, method).side_effect = [
            MahaVidyutAuthenticationError("Session expired"),
            {"source": source},
        ]

    with caplog.at_level("DEBUG", logger=coordinator_module.__name__):
        result = await automatic._async_update_data()

    assert set(result) == set(ENDPOINTS)
    client.async_login.assert_awaited_once_with(
        "synthetic-consumer", "synthetic-password"
    )
    client.set_account.assert_called_once_with(client.async_login.return_value)
    assert client.async_get_latest.await_args_list[0].args == (
        "synthetic-consumer",
        12,
        1,
    )
    assert client.async_get_latest.await_args_list[1].args == (
        "synthetic-consumer",
        99,
        3,
    )
    assert "synthetic-password" not in caplog.text
    assert "new-token" not in caplog.text
    assert "new-client" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [(99, 3), (0, 0)])
async def test_renewed_session_is_persisted_and_slow_cache_is_refreshed(
    automatic, client, clock, monkeypatch, metadata
):
    await automatic._async_update_data()
    client.async_login.assert_not_awaited()
    clock[0] += timedelta(minutes=15)
    account = MahaVidyutAccount("synthetic-consumer", "new-token", *metadata)
    client.async_login.return_value = account
    client.async_get_latest.side_effect = [
        MahaVidyutAuthenticationError("Session expired"),
        {"source": "latest"},
    ]
    entry = SimpleNamespace(
        data={
            "access_token": "old-token",
            "client_id": "old-client",
            "password": "synthetic-password",
            "auto_reauthenticate": True,
        }
    )
    automatic.config_entry = entry
    updater = MagicMock()
    monkeypatch.setattr(
        automatic.hass,
        "config_entries",
        SimpleNamespace(async_update_entry=updater),
        raising=False,
    )

    result = await automatic._async_update_data()

    assert set(result) == set(ENDPOINTS)
    assert client.async_get_recent_bill.await_count == 2
    assert client.async_get_mdi.await_count == 2
    updater.assert_called_once_with(
        entry,
        data={
            **entry.data,
            "access_token": "new-token",
            "client_id": None,
            "meter_id": metadata[0] or 12,
            "phase": metadata[1] or 1,
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config",
    [
        {"password": "private"},
        {"auto_reauthenticate": False, "password": "private"},
        {"auto_reauthenticate": True},
        {"auto_reauthenticate": True, "password": ""},
        {"auto_reauthenticate": True, "password": "private", "use_otp": True},
    ],
)
async def test_password_recovery_requires_explicit_opt_in_and_password_login(
    hass, client, config
):
    obj = MahaVidyutDataCoordinator(hass, client, {"login_id": "test-ca", **config})
    client.async_login = AsyncMock()
    client.async_get_latest.side_effect = MahaVidyutAuthenticationError("expired")
    with pytest.raises(ConfigEntryAuthFailed):
        await obj._async_update_data()
    client.async_login.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejected_new_session_cannot_loop_logins(automatic, client):
    client.async_get_latest.side_effect = MahaVidyutAuthenticationError("expired")
    with pytest.raises(ConfigEntryAuthFailed):
        await automatic._async_update_data()
    assert client.async_login.await_count == 1
    assert client.async_get_latest.await_count == 2
    assert automatic._cache == {}


@pytest.mark.asyncio
async def test_rejected_password_starts_manual_reauthentication(automatic, client):
    client.async_get_latest.side_effect = MahaVidyutAuthenticationError("expired")
    client.async_login.side_effect = MahaVidyutAuthenticationError("invalid password")
    with pytest.raises(ConfigEntryAuthFailed):
        await automatic._async_update_data()
    assert client.async_login.await_count == 1
    client.set_account.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [MahaVidyutConnectionError, MahaVidyutProtocolError])
async def test_transient_login_failure_retries_on_next_poll_without_repair(
    automatic, client, error
):
    client.async_get_latest.side_effect = [
        MahaVidyutAuthenticationError("expired"),
        MahaVidyutAuthenticationError("expired"),
        {"source": "latest"},
    ]
    client.async_login.side_effect = [
        error("unavailable"),
        client.async_login.return_value,
    ]
    with pytest.raises(UpdateFailed):
        await automatic._async_update_data()
    client.set_account.assert_not_called()

    result = await automatic._async_update_data()
    assert result["latest"] == {"source": "latest"}
    assert client.async_login.await_count == 2
    client.set_account.assert_called_once()


@pytest.mark.asyncio
async def test_cancellation_during_login_is_propagated(automatic, client):
    client.async_get_latest.side_effect = MahaVidyutAuthenticationError("expired")
    started = asyncio.Event()

    async def login(*args):
        started.set()
        await asyncio.Event().wait()

    client.async_login.side_effect = login
    refresh = asyncio.create_task(automatic._async_update_data())
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
    finally:
        refresh.cancel()
        with pytest.raises(asyncio.CancelledError):
            await refresh
    client.set_account.assert_not_called()
    assert automatic._cache == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("rejection", [401, 403, "encrypted"])
async def test_first_refresh_with_expired_saved_token_recovers_using_real_client(
    hass, monkeypatch, rejection
):
    """Exercise encrypted API responses through HA's actual first-refresh runtime."""

    class Response:
        def __init__(self, payload, status=200):
            self.status = status
            self.payload = payload

        async def text(self):
            return base64.b64encode(
                api_module._aes_encrypt(
                    json.dumps(self.payload).encode(),
                    base64.b64decode(const.RESPONSE_KEY_B64),
                    base64.b64decode(const.RESPONSE_IV_B64),
                )
            ).decode()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class Session:
        def __init__(self):
            self.logins = 0
            self.accepted = 0
            self.rejected = 0

        def post(self, url, *, headers, **kwargs):
            if url.endswith("/Account/Login"):
                self.logins += 1
                assert "Authorization" not in headers
                return Response(
                    {
                        "data": {
                            "caNumber": "synthetic-consumer",
                            "token": "new-token",
                            "clientID": "new-client",
                            "mid": 99,
                            "phase": 3,
                        }
                    }
                )
            if headers["Authorization"] == "Bearer old-token":
                self.rejected += 1
                return Response(
                    {"error": {"description": "Unauthorized"}},
                    status=200 if rejection == "encrypted" else rejection,
                )
            assert headers["Authorization"] == "Bearer new-token"
            assert headers["clientID"] == "new-client"
            self.accepted += 1
            return Response({"data": {"reading": 1}})

    config = {
        "login_id": "synthetic-consumer",
        "meter_id": 12,
        "phase": 1,
        "access_token": "old-token",
        "auto_reauthenticate": True,
        "password": "synthetic-password",
    }
    entry = SimpleNamespace(
        data=config,
        state=ConfigEntryState.SETUP_IN_PROGRESS,
        async_on_unload=MagicMock(),
        async_start_reauth=MagicMock(),
    )

    def save_entry(_entry, *, data):
        entry.data = data

    monkeypatch.setattr(
        hass,
        "config_entries",
        SimpleNamespace(async_update_entry=MagicMock(side_effect=save_entry)),
        raising=False,
    )
    session = Session()
    client = api_module.MahaVidyutClient(session, token=entry.data["access_token"])
    obj = MahaVidyutDataCoordinator(hass, client, entry.data, config_entry=entry)

    await obj.async_config_entry_first_refresh()

    assert obj.last_update_success
    assert set(obj.data) == set(ENDPOINTS)
    assert session.logins == 1
    assert session.rejected == session.accepted == 6
    assert entry.data["access_token"] == "new-token"
    assert entry.data["client_id"] == "new-client"
    entry.async_start_reauth.assert_not_called()

    # A fresh client/coordinator uses the persisted token without another login.
    fresh_client = api_module.MahaVidyutClient(
        session, token=entry.data["access_token"], client_id=entry.data["client_id"]
    )
    restarted = MahaVidyutDataCoordinator(
        hass, fresh_client, entry.data, config_entry=entry
    )
    await restarted.async_config_entry_first_refresh()
    assert restarted.last_update_success
    assert session.logins == 1
    assert session.accepted == 12
