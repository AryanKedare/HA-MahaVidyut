"""Extract only CA number, MID and phase from your OWN HAR capture.

Does not write decrypted data to disk, and intentionally never shows portal
passwords, bearer tokens, refresh tokens, OTPs, or personal contact details.
"""

import argparse
import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("har", type=Path, help="Your privately captured cportal .har file")
    parser.add_argument("--show-consumer", action="store_true", help="Print full CA number")
    args = parser.parse_args()
    data = json.loads(args.har.read_text(encoding="utf-8"))
    key = base64.b64decode("KwbwSVGl080Z6GEmUtu0Yb1Bh6Lix5PLSm+rxikNeJ4=")
    iv = base64.b64decode("4AEItsSgM6pVBM+t+54hnw==")
    for entry in data.get("log", {}).get("entries", []):
        if not entry.get("request", {}).get("url", "").endswith(
            "/api/Account/TwoFactorVerifyOTP"
        ) or entry.get("response", {}).get("status") != 200:
            continue
        raw = entry.get("response", {}).get("content", {}).get("text", "")
        ciphertext = base64.b64decode(raw, validate=True)
        decrypted = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        padded = decrypted.update(ciphertext) + decrypted.finalize()
        unpad = padding.PKCS7(128).unpadder()
        obj = json.loads((unpad.update(padded) + unpad.finalize()).decode())
        user = obj.get("data", {}).get("userDetails", {})
        if user:
            ca = str(user.get("caNumber", ""))
            print("Consumer / CA number:", ca if args.show_consumer else "..." + ca[-4:])
            print("Internal meter ID (MID):", user.get("mid"))
            print("Phase:", user.get("phase"))
            return
    raise SystemExit("No successful TwoFactorVerifyOTP response found in HAR")


if __name__ == "__main__":
    main()
