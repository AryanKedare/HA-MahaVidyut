"""Standalone MahaVidyut tester: Python 3.10+, no Home Assistant required.

Install: python -m pip install aiohttp==3.13.3 cryptography==46.0.5 certifi==2026.7.22
Run:     python maha_vidyut_test.py --report maha-report.json
Probe:   python maha_vidyut_test.py --probe-only

Generated with tools/build_standalone.py from the integration's API and sensor
paths. Passwords, tokens, consumer IDs and raw responses are never reported.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import os
import re
import secrets
import ssl
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from getpass import getpass
from pathlib import Path
from typing import Any

import aiohttp
import certifi
from aiohttp import ClientError, ClientSession
from cryptography.hazmat.primitives import hashes, padding, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asymmetric_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PROTOCOL_SOURCE_SHA256 = (
    "589264ae9fa37c137e626f6b704dd9a4e247b3425ef92940c2ddb75aea2d272e"
)
SENSOR_SOURCE_SHA256 = (
    "beb73b3286d399ad0d0c10ff8b40e1f412dc907e8bf1bfc2332c2313bf394642"
)


BASE_URL = "https://cportal.esami-mhcca.com"


ACCOUNT_SERVICE = "SmartMeterMHAccountAPI"


DASHBOARD_SERVICE = "SmartMeterMHDashboardAPI"


PAYMENT_SERVICE = "SmartMeterMHPaymentAPI"


RESPONSE_KEY_B64 = "KwbwSVGl080Z6GEmUtu0Yb1Bh6Lix5PLSm+rxikNeJ4="


RESPONSE_IV_B64 = "4AEItsSgM6pVBM+t+54hnw=="


REQUEST_PUBLIC_KEY = "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAsgIeBssM68nQVPVOXtHG\nqCJHIKCa7yq/85o/yZm2OMRS6iDiHntqbnXMzNrqubcuM0aDFNZXez1qK4s8DsUo\n2sAo2tdK0csTtEoowSHuIyXJxSpHI3vJ0xhSo16LIOJ/hnKhxj5N1T1hXB0rEFJU\nqUtmogtNJ+k0UyHs6nR7HBmzayxx9hqRWUGh6WSvW+UPoLg9O2vnYW42IqC7vokb\nIehzQU2k5Uhri9T4K0q8YqLVsEtrwwyqkiODLvMakZ1mcruSURVIjhHubLiTK6Fm\n+KQjUKhT5Olldt9n3jp7xu7JZeKLArG4zUvF0Jut0lY6tTefNfxEBhWpYshgsgu4\nwQIDAQAB\n-----END PUBLIC KEY-----"


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


METRICS = (
    {
        "key": "import_energy",
        "source": "latest",
        "path": ("table1", 0, "kWh"),
        "numeric": True,
        "unit": "kWh",
    },
    {
        "key": "export_energy",
        "source": "latest",
        "path": ("table1", 0, "kWhExport"),
        "numeric": True,
        "unit": "kWh",
    },
    {
        "key": "active_power",
        "source": "latest",
        "path": ("table1", 0, "kW"),
        "fallback_source": "live",
        "fallback_path": ("meterData", 0, "kw"),
        "numeric": True,
        "unit": "kW",
    },
    {
        "key": "voltage",
        "source": "latest",
        "path": ("table1", 0, "voltage"),
        "fallback_source": "live",
        "fallback_path": ("meterData", 0, "voltage"),
        "numeric": True,
        "unit": "V",
    },
    {
        "key": "voltage_rn",
        "source": "latest",
        "path": ("table1", 0, "voltage_RN"),
        "fallback_source": "live",
        "fallback_path": ("meterData", 0, "vrn"),
        "numeric": True,
        "unit": "V",
    },
    {
        "key": "voltage_yn",
        "source": "latest",
        "path": ("table1", 0, "voltage_YN"),
        "fallback_source": "live",
        "fallback_path": ("meterData", 0, "vyn"),
        "numeric": True,
        "unit": "V",
    },
    {
        "key": "voltage_bn",
        "source": "latest",
        "path": ("table1", 0, "voltage_BN"),
        "fallback_source": "live",
        "fallback_path": ("meterData", 0, "vbn"),
        "numeric": True,
        "unit": "V",
    },
    {
        "key": "current",
        "source": "latest",
        "path": ("table1", 0, "current"),
        "fallback_source": "live",
        "fallback_path": ("meterData", 0, "current"),
        "numeric": True,
        "unit": "A",
    },
    {
        "key": "frequency",
        "source": "latest",
        "path": ("table1", 0, "frequency"),
        "fallback_source": "live",
        "fallback_path": ("meterData", 0, "frequency"),
        "numeric": True,
        "unit": "Hz",
    },
    {
        "key": "power_factor",
        "source": "latest",
        "path": ("table1", 0, "pf"),
        "fallback_source": "live",
        "fallback_path": ("meterData", 0, "pf"),
        "numeric": True,
        "unit": None,
    },
    {
        "key": "today_consumption",
        "source": "history",
        "path": ("totalAvgConsumptionToday", 0, "total_kwh_imp"),
        "numeric": True,
        "unit": "kWh",
    },
    {
        "key": "current_balance",
        "source": "dashboard",
        "path": ("balanceDetails", "currentBalance"),
        "numeric": True,
        "unit": "INR",
    },
    {
        "key": "connection_status",
        "source": "dashboard",
        "path": ("balanceDetails", "connection_status"),
        "numeric": False,
        "unit": None,
    },
    {
        "key": "current_month_forecast",
        "source": "dashboard",
        "path": ("forecast", "currentMonth", "value"),
        "numeric": True,
        "unit": "kWh",
    },
    {
        "key": "assigned_max_demand",
        "source": "mdi",
        "path": ("assignedMaxDemand",),
        "numeric": False,
        "unit": None,
    },
    {
        "key": "recent_bill_amount",
        "source": "bill",
        "path": ("data", "billAmount"),
        "numeric": True,
        "unit": "INR",
    },
    {
        "key": "recent_bill_consumption",
        "source": "bill",
        "path": ("data", "consumption"),
        "numeric": True,
        "unit": "kWh",
    },
)

# Standalone runner. The generator inserts the integration's protocol above.


def cli_parser():
    parser = argparse.ArgumentParser(
        description="Test MahaVidyut sign-in and the Home Assistant integration's APIs."
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--probe-only",
        action="store_true",
        help="Check TLS and the encrypted authentication rejection without credentials.",
    )
    modes.add_argument(
        "--otp", action="store_true", help="Use the optional SMS login flow."
    )
    parser.add_argument(
        "--consumer", help="Consumer/CA number; otherwise prompted privately."
    )
    parser.add_argument(
        "--meter-id", type=positive_int, help="Override a missing/incorrect MID."
    )
    parser.add_argument(
        "--phase", type=int, choices=(1, 2, 3), help="Override meter phase."
    )
    parser.add_argument(
        "--show-values", action="store_true", help="Show selected meter/billing values."
    )
    parser.add_argument(
        "--report", type=Path, help="Save the diagnostic summary as JSON."
    )
    return parser


def positive_int(value):
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("MID must be a positive integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("MID must be a positive integer")
    return number


def private_input(prompt, environment_name=None):
    value = os.environ.get(environment_name) if environment_name else None
    if value:
        return value
    if not sys.stdin.isatty():
        suffix = f" or set {environment_name}" if environment_name else ""
        raise ValueError(f"Run this script in an interactive terminal{suffix}.")
    return getpass(prompt)


def get_credentials(args):
    consumer = args.consumer or private_input(
        "Consumer / CA number: ", "MAHA_VIDYUT_CONSUMER"
    )
    consumer = consumer.strip()
    password = private_input("MahaVidyut password: ", "MAHA_VIDYUT_PASSWORD")
    if not consumer or not password:
        raise ValueError("Consumer number and password must not be empty.")
    return consumer, password


def trace_config(report):
    """Record paths/status/timing, never headers, bodies or account identifiers."""
    trace = aiohttp.TraceConfig()

    async def started(session, context, params):
        context.started = time.monotonic()

    async def ended(session, context, params):
        report["requests"].append(
            {
                "path": params.url.path,
                "status": params.response.status,
                "seconds": round(time.monotonic() - context.started, 3),
            }
        )

    async def failed(session, context, params):
        report["requests"].append(
            {
                "path": params.url.path,
                "error_type": type(params.exception).__name__,
                "seconds": round(time.monotonic() - context.started, 3),
            }
        )

    trace.on_request_start.append(started)
    trace.on_request_end.append(ended)
    trace.on_request_exception.append(failed)
    return trace


def failure_summary(exc):
    """Only known messages from the shared client are suitable for a report."""
    if isinstance(exc, AESLAuthenticationError):
        category = "authentication"
    elif isinstance(exc, AESLProtocolError):
        category = "protocol"
    elif isinstance(exc, AESLConnectionError):
        category = "connection"
    elif isinstance(exc, AESLApiError):
        category = "server_rejection"
    else:
        category = "unexpected"
    result = {
        "status": "failed",
        "category": category,
        "error_type": type(exc).__name__,
    }
    if isinstance(exc, AESLError):
        result["message"] = str(exc)
    cause = exc.__cause__
    if cause is not None:
        result["cause_type"] = type(cause).__name__
    return result


def lookup_value(root, path):
    value = root
    for part in path:
        if isinstance(part, int):
            if not isinstance(value, list) or part >= len(value):
                return None
            value = value[part]
        elif isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def normalize_metric(value, numeric):
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float, str)):
        return None
    if numeric:
        try:
            number = float(value)
        except (ValueError, TypeError, OverflowError):
            return None
        return number if math.isfinite(number) else None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def metric_summary(data, show_values=False):
    """Check exactly the integration's sensor paths and permitted fallbacks."""
    metrics = {}
    for metric in METRICS:
        candidates = [(metric["source"], metric["path"])]
        if metric.get("fallback_source"):
            candidates.append((metric["fallback_source"], metric["fallback_path"]))
        selected = None
        for source, path in candidates:
            value = normalize_metric(
                lookup_value(data.get(source, {}), path), metric["numeric"]
            )
            if value is not None:
                selected = (value, source)
                break
        item = {"available": selected is not None, "unit": metric.get("unit")}
        if selected:
            item["source"] = selected[1]
            if show_values:
                item["value"] = selected[0]
        metrics[metric["key"]] = item
    return metrics


def data_shape(data):
    """Expose useful field names in known meter containers, never raw values."""
    shape = {}
    for name in (
        "table",
        "table1",
        "meterData",
        "totalAvgConsumptionToday",
        "balanceDetails",
        "forecast",
        "data",
    ):
        if name not in data:
            continue
        value = data[name]
        item = {"type": type(value).__name__}
        if isinstance(value, list):
            item["rows"] = len(value)
            value = value[0] if value else None
        if isinstance(value, dict):
            item["fields"] = sorted(
                key
                for key in value
                if isinstance(key, str)
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key)
            )[:64]
        shape[name] = item
    return shape


async def check_probe(session, report):
    client = AESLClient(session)
    try:
        await client.async_post("Dashboard/LatestIPData", {}, authenticated=False)
    except AESLAuthenticationError:
        report["checks"]["encrypted_authentication_probe"] = {
            "status": "passed",
            "message": "Encrypted response decoded; anonymous request rejected.",
        }
    except AESLApiError:
        report["checks"]["encrypted_authentication_probe"] = {
            "status": "warning",
            "message": "Encrypted response decoded, but rejection was not Unauthorized.",
        }
    except Exception as exc:
        report["checks"]["encrypted_authentication_probe"] = failure_summary(exc)
    else:
        report["checks"]["encrypted_authentication_probe"] = {
            "status": "warning",
            "message": "Anonymous request returned data; account access was not tested.",
        }


async def check_account(session, args, report):
    consumer, password = get_credentials(args)
    client = AESLClient(session)
    try:
        if args.otp:
            await client.async_request_otp(consumer, password)
            code = private_input("SMS code: ")
            account = await client.async_verify_otp(consumer, password, code.strip())
        else:
            account = await client.async_login(consumer, password)
    except AESLError as exc:
        report["checks"]["sign_in"] = failure_summary(exc)
        return
    finally:
        password = ""  # Do not persist credentials in the report or on disk.
    report["checks"]["sign_in"] = {"status": "passed"}
    meter_id = args.meter_id or account.meter_id
    phase = args.phase or account.phase
    report["account_context"] = {
        "meter_id_available": bool(meter_id),
        "phase_available": bool(phase),
        "client_id_available": bool(account.client_id),
        "meter_id_overridden": args.meter_id is not None,
        "phase_overridden": args.phase is not None,
    }
    client = AESLClient(session, token=account.token, client_id=account.client_id)
    jobs = {
        "history": client.async_get_log_history(consumer),
        "bill": client.async_get_recent_bill(consumer),
    }
    if meter_id and phase:
        jobs.update(
            {
                "latest": client.async_get_latest(consumer, meter_id, phase),
                "live": client.async_get_live(consumer, meter_id, phase),
                "dashboard": client.async_get_dashboard(consumer, meter_id, phase),
                "mdi": client.async_get_mdi(consumer, meter_id, phase),
            }
        )
    else:
        for source in ("latest", "live", "dashboard", "mdi"):
            report["checks"][source] = {
                "status": "skipped",
                "message": "Missing meter context; use --meter-id and --phase if known.",
            }
    responses = await asyncio.gather(*jobs.values(), return_exceptions=True)
    data = {}
    for source, response in zip(jobs, responses):
        if isinstance(response, BaseException):
            if isinstance(response, asyncio.CancelledError):
                raise response
            report["checks"][source] = failure_summary(response)
        else:
            data[source] = response
            report["checks"][source] = {
                "status": "passed",
                "shape": data_shape(response),
            }
    report["metrics"] = metric_summary(data, args.show_values)
    report["metrics_available"] = sum(
        item["available"] for item in report["metrics"].values()
    )


def result_code(report):
    checks = report["checks"]
    if any(item.get("category") == "authentication" for item in checks.values()):
        return 1
    if checks.get("sign_in", {}).get("status") == "failed":
        return 1
    reading_statuses = [
        item["status"]
        for name, item in checks.items()
        if name in ("history", "bill", "latest", "live", "dashboard", "mdi")
    ]
    if (
        reading_statuses
        and "passed" not in reading_statuses
        and "failed" in reading_statuses
    ):
        return 1
    statuses = [item["status"] for item in checks.values()]
    if not statuses or all(status == "failed" for status in statuses):
        return 1
    if "failed" in statuses or "warning" in statuses or "skipped" in statuses:
        return 2
    if "metrics" in report and not report.get("metrics_available"):
        return 2
    return 0


async def run_checks(args):
    report = {
        "host": BASE_URL,
        "protocol_source_sha256": PROTOCOL_SOURCE_SHA256,
        "sensor_source_sha256": SENSOR_SOURCE_SHA256,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 (Python 3.10)
        "mode": "probe_only"
        if args.probe_only
        else ("sms_login" if args.otp else "password_login"),
        "values_included": args.show_values,
        "checks": {},
        "requests": [],
    }
    context = ssl.create_default_context(cafile=certifi.where())
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=context),
        timeout=aiohttp.ClientTimeout(total=30),
        trace_configs=[trace_config(report)],
    ) as session:
        if args.probe_only:
            await check_probe(session, report)
        else:
            await check_account(session, args, report)
    code = result_code(report)
    report["result"] = {0: "passed", 1: "failed", 2: "partial"}[code]
    return report, code


def print_summary(report):
    print(f"MahaVidyut test: {report['result'].upper()}")
    for name, item in report["checks"].items():
        message = item.get("message", "")
        print(
            f"  {name}: {item['status'].upper()}" + (f" — {message}" if message else "")
        )
    for item in report["requests"]:
        outcome = f"HTTP {item['status']}" if "status" in item else item["error_type"]
        print(f"  {item['path']}: {outcome}, {item['seconds']:.3f}s")
    if "metrics" in report:
        print(
            f"Sensor fields available: {report['metrics_available']}/{len(report['metrics'])}"
        )
        for name, item in report["metrics"].items():
            value = (
                str(item["value"])
                if "value" in item
                else ("available" if item["available"] else "unavailable")
            )
            print(f"  {name}: {value}")
    if report["result"] != "passed":
        print(
            "Check India VPN connectivity on this machine, credentials, and any failed endpoint."
        )


def main(argv=None):
    parser = cli_parser()
    args = parser.parse_args(argv)
    try:
        report, code = asyncio.run(run_checks(args))
        print_summary(report)
        if args.report:
            args.report.write_text(
                json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
            )
            print(f"Diagnostic report saved to {args.report}")
        return code
    except (EOFError, ValueError, OSError) as exc:
        # These exceptions come from input/report handling, not decrypted API bodies.
        print(f"Cannot run tester: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Test cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
