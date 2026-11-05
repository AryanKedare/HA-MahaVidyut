"""Verify status reflects the primary API's complete encrypted response."""

import asyncio
import base64
import json
from unittest.mock import Mock

import aiohttp
import pytest

from tools import check_server_status as status


def encrypted_response(envelope):
    return status.api._b64(
        status.api._aes_encrypt(
            json.dumps(envelope).encode(),
            base64.b64decode(status.api.RESPONSE_KEY_B64),
            base64.b64decode(status.api.RESPONSE_IV_B64),
        )
    ).encode()


@pytest.mark.parametrize(
    ("http_status", "body", "length", "expected"),
    [
        (
            200,
            encrypted_response(
                {"data": None, "error": {"description": "Unauthorized"}}
            ),
            None,
            (True, "Encrypted anonymous rejection decoded"),
        ),
        (
            200,
            encrypted_response({"data": None, "error": {"description": "Rejected"}}),
            None,
            (True, "Encrypted API rejection decoded"),
        ),
        (
            200,
            encrypted_response({"data": {}, "error": None}),
            None,
            (True, "Encrypted API response decoded"),
        ),
        (
            200,
            b"<html>Portal homepage</html>",
            None,
            (False, "MahaVidyutProtocolError"),
        ),
        (200, b"truncated", 100, (False, "ClientPayloadError")),
        (503, b"Unavailable", None, (False, "HTTP 503")),
        (500, b"Server error", None, (False, "HTTP 500")),
        (302, b"Redirect", None, (False, "HTTP 302")),
    ],
)
async def test_http_probe_requires_complete_api_response(
    monkeypatch, http_status, body, length, expected
):
    requests = []

    async def respond(reader, writer):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            headers = dict(line.split(b": ", 1) for line in head.split(b"\r\n")[1:-2])
            payload = await reader.readexactly(int(headers[b"Content-Length"]))
            requests.append((head, payload))
            writer.write(
                f"HTTP/1.1 {http_status} Probe\r\n"
                f"Content-Length: {length or len(body)}\r\n"
                "Location: /must-not-follow\r\n"
                "Connection: close\r\n\r\n".encode()
                + body
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(respond, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(status, "PROBE_URL", f"http://127.0.0.1:{port}/api/probe")
    monkeypatch.setenv("MAHA_VIDYUT_CONSUMER", "PRIVATE-CA")
    monkeypatch.setenv("MAHA_VIDYUT_PASSWORD", "PRIVATE-PASSWORD")
    async with server:
        async with aiohttp.ClientSession() as session:
            assert await status.check_connection(session) == expected

    assert len(requests) == 1
    head, payload = requests[0]
    assert head.startswith(b"POST /api/probe HTTP/1.1\r\n")
    assert b"Authorization:" not in head
    assert b"Cookie:" not in head
    assert b"Channelid: Android\r\n" in head
    assert payload.count(b".") == 2
    assert b"PRIVATE" not in head + payload


@pytest.mark.parametrize("error", [TimeoutError, aiohttp.ClientConnectionError])
async def test_connection_failure_never_tries_another_host(error):
    session = Mock()
    session.post.side_effect = error("PRIVATE-ERROR")

    assert await status.check_connection(session) == (False, error.__name__)

    session.post.assert_called_once()
    assert session.post.call_args.args[0] == (
        "https://cportal.esami-mhcca.com/"
        "SmartMeterMHDashboardAPI/api/Dashboard/LatestIPData"
    )
    assert session.post.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("passed", [True, False])
async def test_exit_code_and_summary_match_result(
    monkeypatch, tmp_path, capsys, passed
):
    async def result(session):
        assert session.connector._ssl.verify_mode.name == "CERT_REQUIRED"
        assert not session.trust_env
        return passed, "Probe detail"

    monkeypatch.setattr(status, "check_connection", result)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    assert await status.main() == (0 if passed else 1)

    label = "PASSED" if passed else "FAILED"
    assert label in capsys.readouterr().out
    assert f"Primary server connection: {label}" in summary.read_text()
    assert "Probe detail" in summary.read_text()
    assert "+00:00" in summary.read_text()
