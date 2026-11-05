"""Offline cryptography and APK protocol regressions; no server access."""

import asyncio
import base64
import json
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asympad
from cryptography.hazmat.primitives.asymmetric import rsa

from custom_components.aesl_smart_meter import api, const


def test_rsa_aes_request_roundtrip():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_der = private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    original = {"loginID": "synthetic-consumer", "meterID": 12, "phase": 1}
    encoded = api.encrypt_request(original, base64.b64encode(pub_der).decode())
    a, b, c = encoded.split(".")

    def unprotect(part):
        return private.decrypt(
            base64.b64decode(part),
            asympad.OAEP(
                mgf=asympad.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None
            ),
        )

    aes_key = base64.b64decode(unprotect(a))
    iv = base64.b64decode(unprotect(b))
    decrypted = api._aes_decrypt(base64.b64decode(c), aes_key, iv)
    assert json.loads(decrypted) == original
    assert len(a) == 344 and len(b) == 344


def test_fixed_response_key_roundtrip():
    payload = {"data": {"table1": [{"kWh": 126.3}]}, "error": None}
    key = base64.b64decode(const.RESPONSE_KEY_B64)
    iv = base64.b64decode(const.RESPONSE_IV_B64)
    cipher = api._aes_encrypt(json.dumps(payload).encode(), key, iv)
    result = api.unwrap_response(base64.b64encode(cipher).decode())
    assert result["table1"][0]["kWh"] == 126.3


def test_portal_error_is_not_exposed():
    payload = {"data": None, "error": {"secret": "private"}}
    ciphertext = api._aes_encrypt(
        json.dumps(payload).encode(),
        base64.b64decode(const.RESPONSE_KEY_B64),
        base64.b64decode(const.RESPONSE_IV_B64),
    )
    try:
        api.unwrap_response(base64.b64encode(ciphertext).decode())
    except api.MahaVidyutApiError as exc:
        assert "private" not in str(exc)
    else:
        assert False, "Expected MahaVidyutApiError"


def encode_response(payload):
    """Encode synthetic server fixtures with the APK response protocol."""
    ciphertext = api._aes_encrypt(
        json.dumps(payload).encode(),
        base64.b64decode(const.RESPONSE_KEY_B64),
        base64.b64decode(const.RESPONSE_IV_B64),
    )
    return base64.b64encode(ciphertext).decode()


class Response:
    def __init__(self, payload=None, status=200, raw=None):
        self.status = status
        self.raw = (
            raw
            if raw is not None
            else encode_response({"data": payload, "error": None})
        )

    async def text(self):
        return self.raw

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,args,service,endpoint,body",
    [
        (
            "async_get_log_history",
            ("test-ca",),
            const.DASHBOARD_SERVICE,
            "Dashboard/GetLogHisDyn",
            {"loginID": "test-ca"},
        ),
        (
            "async_get_latest",
            ("test-ca", 42, 3),
            const.DASHBOARD_SERVICE,
            "Dashboard/LatestIPData",
            {"loginID": "test-ca", "meterID": 42, "phase": 3},
        ),
        (
            "async_get_live",
            ("test-ca", 42, 3),
            const.DASHBOARD_SERVICE,
            "Dashboard/MeterLiveData",
            {"loginID": "test-ca", "meterID": 42, "phase": 3},
        ),
        (
            "async_get_dashboard",
            ("test-ca", 42, 3),
            const.DASHBOARD_SERVICE,
            "Dashboard",
            {"loginID": "test-ca", "meterID": 42, "phase": 3},
        ),
        (
            "async_get_mdi",
            ("test-ca", 42, 3),
            const.DASHBOARD_SERVICE,
            "Dashboard/MDI",
            {"loginID": "test-ca", "meterID": 42, "phase": 3},
        ),
        (
            "async_get_recent_bill",
            ("test-ca",),
            const.PAYMENT_SERVICE,
            "Payment/MsedclGETRecentBill",
            {"consumerno": "test-ca", "lang": "en"},
        ),
    ],
)
async def test_apk_service_routes_and_request_models(
    method, args, service, endpoint, body
):
    session = Session(Response({"fixture": 1}))
    client = api.MahaVidyutClient(
        session, token="synthetic-token", client_id="synthetic-client"
    )
    with patch.object(
        api, "encrypt_request", return_value="raw.encrypted.body"
    ) as encrypt:
        assert await getattr(client, method)(*args) == {"fixture": 1}
    encrypt.assert_called_once_with(body, const.REQUEST_PUBLIC_KEY)
    url, kwargs = session.calls[0]
    assert url == f"https://cportal.esami-mhcca.com/{service}/api/{endpoint}"
    assert kwargs["data"] == "raw.encrypted.body"
    assert kwargs["headers"] == {
        "Accept": "*/*",
        "Channelid": "Android",
        "Content-Type": "text/plain",
        "Authorization": "Bearer synthetic-token",
        "clientID": "synthetic-client",
    }
    assert kwargs["allow_redirects"] is False
    assert len(session.calls) == 1  # No payment/GetRSA bootstrap request.


@pytest.mark.asyncio
async def test_login_discovers_context_without_sending_stale_token():
    session = Session(
        Response(
            {
                "token": "new-token",
                "caNumber": "test-ca",
                "mid": 42,
                "phase": 3,
                "clientID": "client",
            }
        )
    )
    client = api.MahaVidyutClient(session, token="stale")
    with patch.object(api, "encrypt_request", return_value="cipher") as encrypt:
        result = await client.async_login("test-ca", "synthetic-password")
    assert result == api.MahaVidyutAccount("test-ca", "new-token", 42, 3, "client")
    assert "new-token" not in repr(result)
    encrypt.assert_called_once_with(
        {"loginID": "test-ca", "password": "synthetic-password"},
        const.REQUEST_PUBLIC_KEY,
    )
    assert "Authorization" not in session.calls[0][1]["headers"]
    assert "clientID" not in session.calls[0][1]["headers"]


@pytest.mark.asyncio
async def test_otp_request_and_verification_contract():
    session = Session(Response({"message": "sent"}))
    client = api.MahaVidyutClient(session)
    with patch.object(api, "encrypt_request", return_value="cipher") as encrypt:
        await client.async_request_otp("test-ca", "test-password")
    encrypt.assert_called_once_with(
        {"loginID": "test-ca", "password": "test-password"}, const.REQUEST_PUBLIC_KEY
    )
    assert session.calls[0][0].endswith("/api/Account/TwoFactorVerifyUser")
    session.response = Response(
        {"userDetails": {"token": "new-token", "mid": 42, "phase": 1}}
    )
    with patch.object(api, "encrypt_request", return_value="cipher") as encrypt:
        result = await client.async_verify_otp("test-ca", "test-password", "012345")
    assert result.token == "new-token"
    encrypt.assert_called_once_with(
        {
            "loginID": "test-ca",
            "password": "test-password",
            "otp": 12345,
            "smsTypeID": 6,
        },
        const.REQUEST_PUBLIC_KEY,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,error",
    [
        (401, api.MahaVidyutAuthenticationError),
        (403, api.MahaVidyutAuthenticationError),
        (500, api.MahaVidyutConnectionError),
        (302, api.MahaVidyutConnectionError),
    ],
)
async def test_http_failures_do_not_expose_server_response(status, error):
    client = api.MahaVidyutClient(
        Session(Response(status=status, raw="secret-token")), token="test"
    )
    with pytest.raises(error) as caught:
        await client.async_get_log_history("test-ca")
    assert "secret-token" not in str(caught.value)


def test_unauthorized_encrypted_response_triggers_reauthentication():
    encoded = encode_response({"data": None, "error": {"description": "Unauthorized"}})
    with pytest.raises(api.MahaVidyutAuthenticationError):
        api.unwrap_response(encoded)


@pytest.mark.asyncio
async def test_data_cannot_be_queried_without_an_account_session():
    session = Session(Response({}))
    with pytest.raises(api.MahaVidyutAuthenticationError):
        await api.MahaVidyutClient(session).async_get_log_history("test-ca")
    assert not session.calls


@pytest.mark.parametrize(
    "payload",
    [
        {"token": None},
        {"token": " "},
        {"token": "t", "caNumber": "another-ca"},
        {"userDetails": None},
    ],
)
def test_invalid_authentication_response_is_rejected(payload):
    with pytest.raises(api.MahaVidyutAuthenticationError):
        api.parse_account(payload, "test-ca")


@pytest.mark.parametrize(
    "context",
    [
        {"mid": -1},
        {"mid": 1.5},
        {"mid": True},
        {"mid": "NaN"},
        {"phase": 4},
        {"phase": True},
        {"phase": 1.5},
    ],
)
def test_malformed_meter_context_is_rejected(context):
    with pytest.raises(api.MahaVidyutProtocolError):
        api.parse_account({"token": "t", **context}, "test-ca")


@pytest.mark.parametrize("raw", ["", "not-base64", "AAAA", "e30=", '"AAAA"'])
def test_malformed_ciphertext_is_a_protocol_error(raw):
    with pytest.raises(api.MahaVidyutProtocolError):
        api.unwrap_response(raw)


@pytest.mark.parametrize("payload", [[], {"data": []}, {"data": None}, {"data": "x"}])
def test_malformed_envelopes_are_rejected(payload):
    with pytest.raises(api.MahaVidyutError):
        api.unwrap_response(encode_response(payload))


@pytest.mark.asyncio
async def test_transport_timeouts_are_normalized():
    class TimeoutSession:
        def post(self, *args, **kwargs):
            raise TimeoutError

    with pytest.raises(api.MahaVidyutConnectionError):
        await api.MahaVidyutClient(TimeoutSession(), token="t").async_get_log_history(
            "test-ca"
        )


def test_bundled_public_key_is_a_2048_bit_rsa_key():
    key = serialization.load_pem_public_key(const.REQUEST_PUBLIC_KEY.encode())
    assert isinstance(key, rsa.RSAPublicKey)
    assert key.key_size == 2048


@pytest.mark.asyncio
@pytest.mark.parametrize("client_id", [None, "new-client"])
async def test_renewed_session_replaces_token_and_client_headers(client_id):
    session = Session(Response({"fixture": 1}))
    client = api.MahaVidyutClient(session, token="old-token", client_id="old-client")
    client.set_account(
        api.MahaVidyutAccount("test-ca", "new-token", client_id=client_id)
    )
    await client.async_get_log_history("test-ca")
    headers = session.calls[0][1]["headers"]
    assert headers["Authorization"] == "Bearer new-token"
    if client_id is None:
        assert "clientID" not in headers
    else:
        assert headers["clientID"] == "new-client"


class FailoverSession:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return response


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError(),
        api.ClientError("PRIVATE-CONNECTION-DETAIL"),
        Response(status=408),
        Response(status=500),
        Response(status=502),
        Response(status=503),
        Response(status=504),
        Response(raw="<html>PRIVATE-MAINTENANCE-PAGE</html>"),
    ],
)
async def test_unavailable_primary_uses_backup_with_same_encrypted_request(failure):
    session = FailoverSession(failure, Response({"reading": 1}))
    client = api.MahaVidyutClient(session, token="test-token", client_id="test-client")
    with patch.object(api, "encrypt_request", return_value="encrypted-body") as encrypt:
        assert await client.async_get_log_history("test-ca") == {"reading": 1}

    assert [url for url, _ in session.calls] == [
        "https://cportal.esami-mhcca.com/SmartMeterMHDashboardAPI/api/Dashboard/GetLogHisDyn",
        "https://cportal.aeslami-mh.com/api/Dashboard/GetLogHisDyn",
    ]
    primary_kwargs = session.calls[0][1]
    backup_kwargs = session.calls[1][1]
    assert primary_kwargs["data"] == backup_kwargs["data"]
    assert primary_kwargs["headers"]["Channelid"] == "Android"
    assert "Channelid" not in backup_kwargs["headers"]
    assert {k: v for k, v in primary_kwargs["headers"].items() if k != "Channelid"} == (
        backup_kwargs["headers"]
    )
    assert session.calls[1][1]["headers"]["Authorization"] == "Bearer test-token"
    assert session.calls[1][1]["allow_redirects"] is False
    assert "ssl" not in session.calls[1][1]
    encrypt.assert_called_once()


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 302])
async def test_auth_and_non_transient_http_errors_do_not_fail_over(status):
    session = FailoverSession(Response(status=status, raw="PRIVATE-RESPONSE"))
    error = (
        api.MahaVidyutAuthenticationError
        if status in (401, 403)
        else api.MahaVidyutConnectionError
    )
    with pytest.raises(error) as caught:
        await api.MahaVidyutClient(session, token="test-token").async_get_log_history(
            "test-ca"
        )
    assert len(session.calls) == 1
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize(
    "description,error",
    [
        ("Unauthorized", api.MahaVidyutAuthenticationError),
        ("Denied", api.MahaVidyutApiError),
    ],
)
async def test_encrypted_account_rejections_do_not_fail_over(description, error):
    session = FailoverSession(
        Response(
            raw=encode_response({"data": None, "error": {"description": description}})
        )
    )
    with pytest.raises(error):
        await api.MahaVidyutClient(session, token="test-token").async_get_log_history(
            "test-ca"
        )
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "failures,error",
    [
        (
            (TimeoutError(), api.ClientError("PRIVATE-DETAIL")),
            api.MahaVidyutConnectionError,
        ),
        ((Response(status=503), Response(status=502)), api.MahaVidyutConnectionError),
        (
            (Response(raw="PRIVATE-A"), Response(raw="PRIVATE-B")),
            api.MahaVidyutProtocolError,
        ),
    ],
)
async def test_both_hosts_failing_is_bounded_and_sanitized(failures, error):
    session = FailoverSession(*failures)
    with pytest.raises(error) as caught:
        await api.MahaVidyutClient(session, token="test-token").async_get_log_history(
            "test-ca"
        )
    assert len(session.calls) == 2
    assert "PRIVATE" not in str(caught.value)


async def test_working_backup_is_reused_and_primary_can_recover():
    session = FailoverSession(
        TimeoutError(),
        Response({"reading": 1}),
        Response({"reading": 2}),
        TimeoutError(),
        Response({"reading": 3}),
        Response({"reading": 4}),
    )
    client = api.MahaVidyutClient(session, token="test-token")
    for value in range(1, 5):
        assert await client.async_get_log_history("test-ca") == {"reading": value}
    assert ["/".join(url.split("/")[:3]) for url, _ in session.calls] == [
        const.BASE_URL,
        const.BACKUP_URL,
        const.BACKUP_URL,
        const.BACKUP_URL,
        const.BASE_URL,
        const.BASE_URL,
    ]


async def test_backup_login_keeps_host_and_replacement_session_for_readings():
    session = FailoverSession(
        TimeoutError(),
        Response(
            {"token": "new-token", "caNumber": "test-ca", "clientID": "new-client"}
        ),
        Response({"bill": 1}),
    )
    client = api.MahaVidyutClient(session, token="old-token")
    account = await client.async_login("test-ca", "synthetic-password")
    client.set_account(account)
    assert await client.async_get_recent_bill("test-ca") == {"bill": 1}
    assert session.calls[1][0] == (f"{const.BACKUP_URL}/api/Account/Login")
    assert session.calls[2][0] == (
        f"{const.BACKUP_URL}/api/Payment/MsedclGETRecentBill"
    )
    assert all(
        "Authorization" not in kwargs["headers"] for _, kwargs in session.calls[:2]
    )
    assert session.calls[2][1]["headers"]["Authorization"] == "Bearer new-token"
    assert session.calls[2][1]["headers"]["clientID"] == "new-client"


async def test_explicit_backup_url_is_tried_first():
    session = FailoverSession(Response({"reading": 1}))
    client = api.MahaVidyutClient(session, const.BACKUP_URL + "/", token="test-token")
    await client.async_get_log_history("test-ca")
    assert session.calls[0][0].startswith(const.BACKUP_URL + "/api/")
    assert "Channelid" not in session.calls[0][1]["headers"]
    assert len(session.calls) == 1


async def test_backup_anonymous_probe_matches_live_web_gateway_contract():
    session = FailoverSession(
        Response(
            raw=encode_response(
                {"data": None, "error": {"description": "Unauthorized"}}
            )
        )
    )
    client = api.MahaVidyutClient(session, const.BACKUP_URL)
    with pytest.raises(api.MahaVidyutAuthenticationError):
        await client.async_post("Dashboard/LatestIPData", {}, authenticated=False)

    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url == "https://cportal.aeslami-mh.com/api/Dashboard/LatestIPData"
    assert kwargs["headers"] == {"Accept": "*/*", "Content-Type": "text/plain"}
    assert kwargs["allow_redirects"] is False


async def test_custom_url_does_not_forward_credentials_to_public_hosts():
    session = FailoverSession(TimeoutError())
    client = api.MahaVidyutClient(
        session, "https://custom.example/", token="test-token"
    )
    with pytest.raises(api.MahaVidyutConnectionError):
        await client.async_get_log_history("test-ca")
    assert len(session.calls) == 1
    assert session.calls[0][0].startswith("https://custom.example/SmartMeter")


async def test_cancelled_request_does_not_start_backup_request():
    session = FailoverSession(asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await api.MahaVidyutClient(session, token="test-token").async_get_log_history(
            "test-ca"
        )
    assert len(session.calls) == 1
