"""Credential, OTP and reauthentication regressions with real HA classes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import AbortFlow

from custom_components.aesl_smart_meter import config_flow
from custom_components.aesl_smart_meter.api import (
    AESLAccount,
    AESLAuthenticationError,
    AESLConnectionError,
    AESLProtocolError,
)


@pytest_asyncio.fixture
async def flow(tmp_path, monkeypatch):
    hass = HomeAssistant(str(tmp_path))
    obj = config_flow.AESLSmartMeterConfigFlow()
    obj.hass = hass
    obj.async_set_unique_id = AsyncMock()
    obj._abort_if_unique_id_configured = MagicMock()
    monkeypatch.setattr(config_flow, "async_get_clientsession", MagicMock())
    yield obj
    await hass.async_stop()


@pytest.fixture
def client(monkeypatch):
    account = AESLAccount("test-ca", "synthetic-token", 42, 3, "synthetic-client")
    fake = SimpleNamespace(
        async_login=AsyncMock(return_value=account),
        async_request_otp=AsyncMock(),
        async_verify_otp=AsyncMock(return_value=account),
    )
    monkeypatch.setattr(config_flow, "AESLClient", MagicMock(return_value=fake))
    return fake


@pytest.mark.asyncio
async def test_login_discovers_meter_without_storing_password(flow, client):
    result = await flow.async_step_user(
        {"login_id": " test-ca ", "password": "private"}
    )
    assert result["type"] == "create_entry"
    assert result["data"] == {
        "login_id": "test-ca",
        "access_token": "synthetic-token",
        "client_id": "synthetic-client",
        "meter_id": 42,
        "phase": 3,
        "use_otp": False,
    }
    assert "private" not in repr(result)
    assert flow._password == ""
    client.async_login.assert_awaited_once_with("test-ca", "private")
    client.async_request_otp.assert_not_called()
    flow.async_set_unique_id.assert_awaited_once_with("test-ca")


@pytest.mark.asyncio
@pytest.mark.parametrize("consumer", ["", "  "])
async def test_empty_consumer_never_contacts_service(flow, client, consumer):
    result = await flow.async_step_user({"login_id": consumer, "password": "private"})
    assert result["errors"] == {"login_id": "invalid_consumer"}
    client.async_login.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_consumer_checked_before_login(flow, client):
    flow._abort_if_unique_id_configured.side_effect = AbortFlow("already_configured")
    with pytest.raises(AbortFlow):
        await flow.async_step_user({"login_id": "test-ca", "password": "private"})
    client.async_login.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,code",
    [
        (AESLAuthenticationError("denied"), "invalid_auth"),
        (AESLConnectionError("offline"), "cannot_connect"),
        (AESLProtocolError("bad response"), "invalid_response"),
    ],
)
async def test_login_failure_returns_form_without_password(flow, client, error, code):
    client.async_login.side_effect = error
    result = await flow.async_step_user({"login_id": "test-ca", "password": "private"})
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": code}
    assert "private" not in repr(result)
    assert flow._password == ""


@pytest.mark.asyncio
async def test_optional_sms_retry_then_drops_password(flow, client):
    result = await flow.async_step_user(
        {"login_id": "test-ca", "password": "private", "use_otp": True}
    )
    assert result["step_id"] == "otp"
    assert "private" not in repr(result)
    client.async_request_otp.assert_awaited_once_with("test-ca", "private")
    client.async_login.assert_not_called()
    client.async_verify_otp.side_effect = AESLAuthenticationError("bad code")
    result = await flow.async_step_otp({"otp": "bad"})
    assert result["errors"] == {"base": "invalid_otp"}
    client.async_verify_otp.side_effect = None
    result = await flow.async_step_otp({"otp": "012345"})
    assert result["type"] == "create_entry"
    assert flow._password == ""
    assert "private" not in repr(result)
    assert "012345" not in repr(result)


@pytest.mark.asyncio
async def test_reauth_updates_existing_entry(flow, client):
    entry = SimpleNamespace(data={"login_id": "test-ca", "access_token": "expired"})
    flow._get_reauth_entry = MagicMock(return_value=entry)
    flow.async_update_reload_and_abort = MagicMock(
        return_value={"type": "abort", "reason": "reauth_successful"}
    )
    first = await flow.async_step_reauth(entry.data)
    assert first["step_id"] == "user"
    result = await flow.async_step_user({"login_id": "test-ca", "password": "private"})
    assert result["reason"] == "reauth_successful"
    flow._abort_if_unique_id_configured.assert_not_called()
    assert (
        flow.async_update_reload_and_abort.call_args.kwargs["data_updates"][
            "access_token"
        ]
        == "synthetic-token"
    )


@pytest.mark.asyncio
async def test_reauth_cannot_switch_consumer(flow, client):
    flow._reauth_entry = SimpleNamespace(data={"login_id": "original-ca"})
    result = await flow.async_step_user({"login_id": "other-ca", "password": "private"})
    assert result["errors"] == {"login_id": "wrong_consumer"}
    client.async_login.assert_not_called()


@pytest.mark.asyncio
async def test_reauth_preserves_known_meter_if_login_metadata_absent(flow, client):
    entry = SimpleNamespace(data={"login_id": "test-ca", "meter_id": 100, "phase": 3})
    flow._reauth_entry = entry
    flow.async_update_reload_and_abort = MagicMock(
        return_value={"reason": "reauth_successful"}
    )
    client.async_login.return_value = AESLAccount("test-ca", "new-token")
    await flow.async_step_user({"login_id": "test-ca", "password": "private"})
    updates = flow.async_update_reload_and_abort.call_args.kwargs["data_updates"]
    assert updates["meter_id"] == 100
    assert updates["phase"] == 3
    assert updates["access_token"] == "new-token"


@pytest.mark.asyncio
async def test_missing_meter_metadata_is_collected_after_login(flow, client):
    client.async_login.return_value = AESLAccount("test-ca", "new-token")
    first = await flow.async_step_user({"login_id": "test-ca", "password": "private"})
    assert first["step_id"] == "meter"
    assert "private" not in repr(first)
    assert "new-token" not in repr(first)
    assert flow._password == ""
    result = await flow.async_step_meter({"meter_id": 100, "phase": 3})
    assert result["data"]["meter_id"] == 100
    assert result["data"]["phase"] == 3
    assert flow._account is None


@pytest.mark.asyncio
async def test_unknown_meter_can_be_left_zero_for_history_only(flow, client):
    client.async_login.return_value = AESLAccount("test-ca", "new-token", phase=3)
    await flow.async_step_user({"login_id": "test-ca", "password": "private"})
    result = await flow.async_step_meter({"meter_id": 0, "phase": 3})
    assert result["data"]["meter_id"] == 0
    assert result["data"]["phase"] == 3
