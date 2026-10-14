"""Offline cryptography and APK protocol regressions; no server access."""

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
    except api.AESLApiError as exc:
        assert "private" not in str(exc)
    else:
        assert False, "Expected AESLApiError"


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
    client = api.AESLClient(
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
    client = api.AESLClient(session, token="stale")
    with patch.object(api, "encrypt_request", return_value="cipher") as encrypt:
        result = await client.async_login("test-ca", "synthetic-password")
    assert result == api.AESLAccount("test-ca", "new-token", 42, 3, "client")
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
    client = api.AESLClient(session)
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
        (401, api.AESLAuthenticationError),
        (403, api.AESLAuthenticationError),
        (500, api.AESLConnectionError),
        (302, api.AESLConnectionError),
    ],
)
async def test_http_failures_do_not_expose_server_response(status, error):
    client = api.AESLClient(
        Session(Response(status=status, raw="secret-token")), token="test"
    )
    with pytest.raises(error) as caught:
        await client.async_get_log_history("test-ca")
    assert "secret-token" not in str(caught.value)


def test_unauthorized_encrypted_response_triggers_reauthentication():
    encoded = encode_response({"data": None, "error": {"description": "Unauthorized"}})
    with pytest.raises(api.AESLAuthenticationError):
        api.unwrap_response(encoded)


@pytest.mark.asyncio
async def test_data_cannot_be_queried_without_an_account_session():
    session = Session(Response({}))
    with pytest.raises(api.AESLAuthenticationError):
        await api.AESLClient(session).async_get_log_history("test-ca")
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
    with pytest.raises(api.AESLAuthenticationError):
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
    with pytest.raises(api.AESLProtocolError):
        api.parse_account({"token": "t", **context}, "test-ca")


@pytest.mark.parametrize("raw", ["", "not-base64", "AAAA", "e30=", '"AAAA"'])
def test_malformed_ciphertext_is_a_protocol_error(raw):
    with pytest.raises(api.AESLProtocolError):
        api.unwrap_response(raw)


@pytest.mark.parametrize("payload", [[], {"data": []}, {"data": None}, {"data": "x"}])
def test_malformed_envelopes_are_rejected(payload):
    with pytest.raises(api.AESLError):
        api.unwrap_response(encode_response(payload))


@pytest.mark.asyncio
async def test_transport_timeouts_are_normalized():
    class TimeoutSession:
        def post(self, *args, **kwargs):
            raise TimeoutError

    with pytest.raises(api.AESLConnectionError):
        await api.AESLClient(TimeoutSession(), token="t").async_get_log_history(
            "test-ca"
        )


def test_bundled_public_key_is_a_2048_bit_rsa_key():
    key = serialization.load_pem_public_key(const.REQUEST_PUBLIC_KEY.encode())
    assert isinstance(key, rsa.RSAPublicKey)
    assert key.key_size == 2048
