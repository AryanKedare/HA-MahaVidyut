"""Unofficial AESL Smart Meter portal API.

Reconstructed from the portal's Interop.js and WebCIL client; does not
implement captcha/OTP login and should be used only with your own account.
"""

from __future__ import annotations

import asyncio
import base64
import json
import secrets
from typing import Any

from aiohttp import ClientError, ClientSession
from cryptography.hazmat.primitives import padding, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asymmetric_padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .const import BASE_URL, RESPONSE_IV_B64, RESPONSE_KEY_B64


class AESLError(Exception):
    """Base portal error; messages must not include credentials or payloads."""


class AESLConnectionError(AESLError):
    """Connection or HTTP error."""


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
            cipher, base64.b64decode(RESPONSE_KEY_B64), base64.b64decode(RESPONSE_IV_B64)
        )
        return json.loads(plain)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise AESLProtocolError("Unable to decode encrypted response") from exc


def encrypt_request(body: Any, public_key_b64: str) -> str:
    """Return RSA-OAEP(AES key).RSA-OAEP(IV).AES-256-CBC(JSON).

    The browser uses JSCryptoInterop.encryptSymmetric then encryptAsymmetric.
    The RSA plaintext is the base64 *string* of the AES key/IV.
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
        raise AESLApiError("Portal rejected request")
    data = obj.get("data")
    if data is None:
        raise AESLApiError("Portal returned no data")
    if not isinstance(data, dict):
        raise AESLProtocolError("Response data was not an object")
    return data


class AESLClient:
    """Simple read-only portal client."""

    def __init__(self, session: ClientSession, base_url: str = BASE_URL) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._public_key: str | None = None
        self._key_lock = asyncio.Lock()

    async def _http_get(self, endpoint: str) -> str:
        try:
            async with self._session.get(
                f"{self._base_url}/api/{endpoint}",
                headers={"Accept": "application/json"},
                timeout=20,
            ) as response:
                if response.status != 200:
                    raise AESLConnectionError(f"Portal GET returned HTTP {response.status}")
                return await response.text()
        except (ClientError, asyncio.TimeoutError) as exc:
            raise AESLConnectionError("Portal GET connection failed") from exc

    async def async_get_rsa_key(self, force: bool = False) -> str:
        """Retrieve the server RSA SPKI key using the encrypted GET protocol."""
        async with self._key_lock:
            if self._public_key and not force:
                return self._public_key
            result = unwrap_response(await self._http_get("Account/GetRSA"))
            key = result.get("rsa_key")
            if not isinstance(key, str) or not key:
                raise AESLProtocolError("GetRSA response does not contain rsa_key")
            self._public_key = key
            return key

    async def async_post(self, endpoint: str, body: dict[str, Any], *,
                         extra_headers: dict[str, str] | None = None) -> dict[str, Any]:
        key = await self.async_get_rsa_key()
        encrypted_body = encrypt_request(body, key)
        headers = {"Accept": "application/json", "Content-Type": "text/plain; charset=utf-8"}
        if extra_headers:
            headers.update(extra_headers)
        try:
            async with self._session.post(
                f"{self._base_url}/api/{endpoint}",
                data=encrypted_body,
                headers=headers,
                timeout=30,
            ) as response:
                if response.status != 200:
                    raise AESLConnectionError(f"Portal POST returned HTTP {response.status}")
                raw = await response.text()
            return unwrap_response(raw)
        except (ClientError, asyncio.TimeoutError) as exc:
            raise AESLConnectionError("Portal POST connection failed") from exc

    async def async_get_log_history(self, login_id: str) -> dict[str, Any]:
        return await self.async_post("Dashboard/GetLogHisDyn", {"loginID": login_id})

    async def async_get_latest(self) -> dict[str, Any]:
        # LatestIPDataRequest is an empty request model in WebCIL.
        return await self.async_post("Dashboard/LatestIPData", {})

    async def async_get_dashboard(self, login_id: str, meter_id: int, phase: int) -> dict[str, Any]:
        return await self.async_post(
            "Dashboard/", {"loginID": login_id, "meterID": meter_id, "phase": phase}
        )

    async def async_get_mdi(self, login_id: str, meter_id: int, phase: int) -> dict[str, Any]:
        return await self.async_post(
            "Dashboard/MDI", {"loginID": login_id, "meterID": meter_id, "phase": phase}
        )

    async def async_get_recent_bill(self, login_id: str) -> dict[str, Any]:
        # MsedclGETRecentBillRequest: consumerno + lang; confirm locale if needed.
        return await self.async_post(
            "Payment/MsedclGETRecentBill", {"consumerno": login_id, "lang": 1}
        )
