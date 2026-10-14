"""Read-only MahaVidyut API client reconstructed from the Android APK."""

from __future__ import annotations

import base64
import json
import secrets
from dataclasses import dataclass, field
from typing import Any

from aiohttp import ClientError, ClientSession
from cryptography.hazmat.primitives import hashes, padding, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asymmetric_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .const import (
    ACCOUNT_SERVICE,
    BASE_URL,
    DASHBOARD_SERVICE,
    PAYMENT_SERVICE,
    REQUEST_PUBLIC_KEY,
    RESPONSE_IV_B64,
    RESPONSE_KEY_B64,
)


class AESLError(Exception):
    """Base portal error; messages must not include credentials or payloads."""


class AESLConnectionError(AESLError):
    """Connection or HTTP error."""


class AESLAuthenticationError(AESLError):
    """The account session is absent, expired, or rejected."""


class AESLProtocolError(AESLError):
    """Unexpected cipher or server response."""


class AESLApiError(AESLError):
    """The server returned an application error."""


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _aes_encrypt(plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return enc.update(padded) + enc.finalize()


def _aes_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = dec.update(ciphertext) + dec.finalize()
    unpad = padding.PKCS7(128).unpadder()
    return unpad.update(padded) + unpad.finalize()


def decrypt_response(response: str) -> Any:
    """Decrypt the portal's base64 AES-CBC response, return parsed JSON.

    No authenticated encryption: don't trust the contents beyond normal
    application validation. Always communicate using HTTPS with TLS verification.
    """
    try:
        cipher = base64.b64decode(response, validate=True)
        plain = _aes_decrypt(
            cipher,
            base64.b64decode(RESPONSE_KEY_B64),
            base64.b64decode(RESPONSE_IV_B64),
        )
        return json.loads(plain)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise AESLProtocolError("Unable to decode encrypted response") from exc


def encrypt_request(body: Any, public_key_b64: str) -> str:
    """Return RSA-OAEP(AES key).RSA-OAEP(IV).AES-256-CBC(JSON).

    The APK RSA-encrypts the base64 *strings* of the AES key and IV using
    OAEP with SHA-256, after encrypting the JSON with AES-256-CBC.
    """
    try:
        if public_key_b64.startswith("-----BEGIN"):
            public_key = serialization.load_pem_public_key(public_key_b64.encode())
        else:
            public_key = serialization.load_der_public_key(
                base64.b64decode(public_key_b64, validate=True)
            )
        aes_key = secrets.token_bytes(32)
        iv = secrets.token_bytes(16)
        payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
        encrypted = _aes_encrypt(payload, aes_key, iv)

        def protect(text: str) -> str:
            return _b64(
                public_key.encrypt(
                    text.encode("utf-8"),
                    asymmetric_padding.OAEP(
                        mgf=asymmetric_padding.MGF1(algorithm=hashes.SHA256()),
                        algorithm=hashes.SHA256(),
                        label=None,
                    ),
                )
            )

        return ".".join((protect(_b64(aes_key)), protect(_b64(iv)), _b64(encrypted)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise AESLProtocolError("Invalid RSA public key") from exc


def unwrap_response(encoded: str) -> dict[str, Any]:
    """Normalize {data, error} envelopes from the AESL API."""
    obj = decrypt_response(encoded)
    if not isinstance(obj, dict):
        raise AESLProtocolError("Response was not a JSON object")
    error = obj.get("error")
    if error:
        if isinstance(error, dict) and error.get("description") == "Unauthorized":
            raise AESLAuthenticationError("MahaVidyut session expired")
        raise AESLApiError("Portal rejected request")
    data = obj.get("data")
    if data is None:
        raise AESLApiError("Portal returned no data")
    if not isinstance(data, dict):
        raise AESLProtocolError("Response data was not an object")
    return data


@dataclass(frozen=True)
class AESLAccount:
    """Validated login context; exclude secrets from representations."""

    login_id: str
    token: str = field(repr=False)
    meter_id: int = 0
    phase: int = 0
    client_id: str | None = None


def parse_account(data: dict[str, Any], login_id: str) -> AESLAccount:
    """Accept the Login user or the TwoFactorVerifyOTP userDetails model."""
    user = data.get("userDetails", data)
    if not isinstance(user, dict):
        raise AESLAuthenticationError("MahaVidyut returned no account session")
    token = user.get("token")
    consumer = user.get("caNumber")
    if not isinstance(token, str) or not token.strip():
        raise AESLAuthenticationError("MahaVidyut returned no access token")
    if consumer is not None and str(consumer).strip() != login_id:
        raise AESLAuthenticationError("MahaVidyut returned a different consumer")
    try:
        meter_id = int(user.get("mid") or 0)
        phase = int(user.get("phase") or 0)
        if isinstance(user.get("mid"), bool) or isinstance(user.get("phase"), bool):
            raise TypeError
        if meter_id < 0 or phase not in (0, 1, 2, 3):
            raise ValueError
        # Do not silently truncate a fractional meter identifier or phase.
        if user.get("mid") is not None and float(user["mid"]) != meter_id:
            raise ValueError
        if user.get("phase") is not None and float(user["phase"]) != phase:
            raise ValueError
    except (ValueError, TypeError, OverflowError) as exc:
        raise AESLProtocolError("MahaVidyut returned invalid meter context") from exc
    client_id = user.get("clientID")
    if client_id is not None and not isinstance(client_id, str):
        raise AESLProtocolError("MahaVidyut returned an invalid client ID")
    return AESLAccount(login_id, token.strip(), meter_id, phase, client_id or None)


class AESLClient:
    """Authenticated MahaVidyut client; no payments or account writes."""

    def __init__(
        self,
        session: ClientSession,
        base_url: str = BASE_URL,
        *,
        token: str | None = None,
        client_id: str | None = None,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client_id = client_id

    async def async_post(
        self,
        endpoint: str,
        body: dict[str, Any],
        *,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        """Send the APK's encrypted wire format to the appropriate service."""
        if authenticated and not self._token:
            raise AESLAuthenticationError("Sign in to your MahaVidyut account")
        controller = endpoint.split("/", 1)[0]
        service = {
            "Account": ACCOUNT_SERVICE,
            "Dashboard": DASHBOARD_SERVICE,
            "Payment": PAYMENT_SERVICE,
        }.get(controller)
        if service is None:
            raise AESLProtocolError("Unsupported MahaVidyut service")
        encrypted_body = encrypt_request(body, REQUEST_PUBLIC_KEY)
        headers = {
            "Accept": "*/*",
            "Channelid": "Android",
            "Content-Type": "text/plain",
        }
        if authenticated:
            headers["Authorization"] = f"Bearer {self._token}"
            if self._client_id:
                headers["clientID"] = self._client_id
        try:
            async with self._session.post(
                f"{self._base_url}/{service}/api/{endpoint}",
                data=encrypted_body,
                headers=headers,
                timeout=30,
                allow_redirects=False,
            ) as response:
                if response.status in (401, 403):
                    raise AESLAuthenticationError("MahaVidyut authentication rejected")
                if response.status != 200:
                    raise AESLConnectionError(
                        f"MahaVidyut POST returned HTTP {response.status}"
                    )
                raw = await response.text()
            return unwrap_response(raw)
        except (TimeoutError, ClientError) as exc:
            raise AESLConnectionError("MahaVidyut connection failed") from exc

    async def async_login(self, login_id: str, password: str) -> AESLAccount:
        """Use the Maharashtra app's password login and discover meter context."""
        try:
            data = await self.async_post(
                "Account/Login",
                {"loginID": login_id, "password": password},
                authenticated=False,
            )
        except AESLApiError as exc:
            raise AESLAuthenticationError("MahaVidyut sign-in rejected") from exc
        return parse_account(data, login_id)

    async def async_request_otp(self, login_id: str, password: str) -> None:
        """Start the APK's optional SMS verification flow."""
        try:
            await self.async_post(
                "Account/TwoFactorVerifyUser",
                {"loginID": login_id, "password": password},
                authenticated=False,
            )
        except AESLApiError as exc:
            raise AESLAuthenticationError("MahaVidyut verification rejected") from exc

    async def async_verify_otp(
        self, login_id: str, password: str, otp: str
    ) -> AESLAccount:
        """Verify SMS code; smsTypeID 6 is the APK's login2FA request."""
        if not otp.isascii() or not otp.isdecimal():
            raise AESLAuthenticationError("Enter a numeric SMS code")
        try:
            data = await self.async_post(
                "Account/TwoFactorVerifyOTP",
                {
                    "loginID": login_id,
                    "password": password,
                    "otp": int(otp),
                    "smsTypeID": 6,
                },
                authenticated=False,
            )
        except AESLApiError as exc:
            raise AESLAuthenticationError("MahaVidyut SMS code rejected") from exc
        return parse_account(data, login_id)

    async def async_get_log_history(self, login_id: str) -> dict[str, Any]:
        return await self.async_post("Dashboard/GetLogHisDyn", {"loginID": login_id})

    async def async_get_latest(
        self, login_id: str, meter_id: int, phase: int
    ) -> dict[str, Any]:
        return await self.async_post(
            "Dashboard/LatestIPData",
            {"loginID": login_id, "meterID": meter_id, "phase": phase},
        )

    async def async_get_live(
        self, login_id: str, meter_id: int, phase: int
    ) -> dict[str, Any]:
        return await self.async_post(
            "Dashboard/MeterLiveData",
            {"loginID": login_id, "meterID": meter_id, "phase": phase},
        )

    async def async_get_dashboard(
        self, login_id: str, meter_id: int, phase: int
    ) -> dict[str, Any]:
        return await self.async_post(
            "Dashboard", {"loginID": login_id, "meterID": meter_id, "phase": phase}
        )

    async def async_get_mdi(
        self, login_id: str, meter_id: int, phase: int
    ) -> dict[str, Any]:
        return await self.async_post(
            "Dashboard/MDI", {"loginID": login_id, "meterID": meter_id, "phase": phase}
        )

    async def async_get_recent_bill(self, login_id: str) -> dict[str, Any]:
        return await self.async_post(
            "Payment/MsedclGETRecentBill", {"consumerno": login_id, "lang": "en"}
        )
