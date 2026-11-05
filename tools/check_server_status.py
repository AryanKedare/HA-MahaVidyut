"""Check the primary MahaVidyut API without credentials or host failover."""

from __future__ import annotations

import asyncio
import os
import ssl
from datetime import UTC, datetime
from pathlib import Path

import aiohttp
import certifi

from tools import maha_vidyut_test as api

PROBE_URL = f"{api.BASE_URL}/{api.DASHBOARD_SERVICE}/api/Dashboard/LatestIPData"


async def check_connection(session: aiohttp.ClientSession) -> tuple[bool, str]:
    """Require a complete, decryptable API reply from this specific host."""
    try:
        async with session.post(
            PROBE_URL,
            data=api.encrypt_request({}, api.REQUEST_PUBLIC_KEY),
            headers={
                "Accept": "*/*",
                "Channelid": "Android",
                "Content-Type": "text/plain",
            },
            timeout=aiohttp.ClientTimeout(total=20),
            allow_redirects=False,
        ) as response:
            if response.status != 200:
                return False, f"HTTP {response.status}"
            raw = await response.text()
        try:
            api.unwrap_response(raw)
        except api.MahaVidyutAuthenticationError:
            return True, "Encrypted anonymous rejection decoded"
        except api.MahaVidyutApiError:
            return True, "Encrypted API rejection decoded"
        return True, "Encrypted API response decoded"
    except (aiohttp.ClientError, TimeoutError, api.MahaVidyutProtocolError) as exc:
        return False, type(exc).__name__


async def main() -> int:
    context = ssl.create_default_context(cafile=certifi.where())
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=context), trust_env=False
    ) as session:
        passed, detail = await check_connection(session)
    status = "PASSED" if passed else "FAILED"
    checked_at = datetime.now(UTC).isoformat(timespec="seconds")
    print(f"Primary server connection {status}: {api.BASE_URL} — {detail}")
    print(f"Checked at {checked_at}")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(
                f"## Primary server connection: {status}\n\n"
                f"- Server: {api.BASE_URL}\n"
                f"- Result: {detail}\n"
                f"- Checked at: {checked_at}\n\n"
                "This anonymous API probe checks connectivity and encrypted "
                "responses. Account sign-in and live-meter data availability "
                "are checked separately.\n"
            )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
