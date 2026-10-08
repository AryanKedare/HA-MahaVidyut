"""Offline regression tests; no portal access or Home Assistant needed."""

import base64
import importlib.util
import json
import pathlib
import sys
import types

from cryptography.hazmat.primitives import hashes, padding, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asympad, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "aesl_smart_meter"
PKG = "aesl_smart_meter"
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(ROOT)]
sys.modules.setdefault(PKG, pkg)
for name in ("const", "api"):
    spec = importlib.util.spec_from_file_location(f"{PKG}.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

from aesl_smart_meter import api, const  # noqa: E402


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
            asympad.OAEP(mgf=asympad.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
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
        json.dumps(payload).encode(), base64.b64decode(const.RESPONSE_KEY_B64),
        base64.b64decode(const.RESPONSE_IV_B64),
    )
    try:
        api.unwrap_response(base64.b64encode(ciphertext).decode())
    except api.AESLApiError as exc:
        assert "private" not in str(exc)
    else:
        assert False, "Expected AESLApiError"
