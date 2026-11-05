"""Standalone tester parity, credential handling and failure regressions."""

import ast
import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import build_standalone
from tools import maha_vidyut_test as tester

ROOT = Path(__file__).resolve().parents[1]


def arguments(*flags):
    return tester.cli_parser().parse_args(list(flags))


class FakeClient:
    calls = []
    failure = None
    account = None

    def __init__(self, session, **kwargs):
        self.kwargs = kwargs

    def set_account(self, account):
        self.account = account

    async def async_login(self, consumer, password):
        self.calls.append(("login", consumer, password))
        if self.failure == "login":
            raise tester.MahaVidyutAuthenticationError("MahaVidyut sign-in rejected")
        return self.account

    async def async_request_otp(self, consumer, password):
        self.calls.append(("request_otp", consumer, password))

    async def async_verify_otp(self, consumer, password, otp):
        self.calls.append(("verify_otp", consumer, password, otp))
        return self.account

    async def response(self, source, args, data):
        self.calls.append((source, *args))
        if self.failure in (source, "all"):
            raise tester.MahaVidyutConnectionError("MahaVidyut POST returned HTTP 500")
        if self.failure == "expired" and source == "live":
            raise tester.MahaVidyutAuthenticationError("MahaVidyut session expired")
        return data

    async def async_get_log_history(self, consumer):
        return await self.response(
            "history", (consumer,), {"totalAvgConsumptionToday": [{"total_kwh_imp": 4}]}
        )

    async def async_get_recent_bill(self, consumer):
        return await self.response(
            "bill",
            (consumer,),
            {
                "data": {
                    "billAmount": 100,
                    "consumption": 10,
                    "consumerName": "PRIVATE-NAME",
                }
            },
        )

    async def async_get_latest(self, *args):
        return await self.response(
            "latest",
            args,
            {
                "table1": [{"kWh": 123, "kWhExport": 0, "voltage": None, "pf": "NaN"}],
                "table": [{"readingDate": "PRIVATE-TIME"}],
            },
        )

    async def async_get_live(self, *args):
        return await self.response(
            "live",
            args,
            {
                "meterData": [
                    {
                        "kw": 1.25,
                        "voltage": 230,
                        "pf": 0.95,
                        "kWh": 122,
                        "meterSerialNo": "PRIVATE-METER",
                    }
                ]
            },
        )

    async def async_get_dashboard(self, *args):
        return await self.response(
            "dashboard",
            args,
            {
                "balanceDetails": {
                    "currentBalance": 100,
                    "connection_status": "Connected",
                }
            },
        )

    async def async_get_mdi(self, *args):
        return await self.response("mdi", args, {"assignedMaxDemand": 8})


@pytest.fixture
def fake_client(monkeypatch):
    FakeClient.calls = []
    FakeClient.failure = None
    FakeClient.account = tester.MahaVidyutAccount(
        "PRIVATE-CA", "PRIVATE-TOKEN", 97654321, 3, "PRIVATE-CLIENT"
    )
    monkeypatch.setattr(tester, "MahaVidyutClient", FakeClient)
    monkeypatch.setenv("MAHA_VIDYUT_CONSUMER", "PRIVATE-CA")
    monkeypatch.setenv("MAHA_VIDYUT_PASSWORD", "PRIVATE-PASSWORD")
    return FakeClient


@pytest.fixture
def report():
    return {"checks": {}, "requests": []}


def trace_parameters(path="/api/Account/Login"):
    return SimpleNamespace(
        url=SimpleNamespace(
            host="cportal.aeslami-mh.com", path=path, query="PRIVATE-QUERY"
        ),
        headers={
            "Accept-Encoding": "gzip, deflate, zstd",
            "Authorization": "PRIVATE-TOKEN",
            "Cookie": "PRIVATE-COOKIE",
        },
        body="PRIVATE-PASSWORD",
        chunk=b"PRIVATE-RESPONSE",
        response=SimpleNamespace(
            status=200,
            headers={
                "Content-Encoding": "gzip",
                "Content-Length": "123",
                "Set-Cookie": "PRIVATE-SESSION",
            },
        ),
        exception=RuntimeError("PRIVATE-ERROR"),
    )


def test_generated_snapshot_matches_current_client_and_sensor_paths():
    assert build_standalone.TARGET.read_text() == build_standalone.render()
    component = ROOT / "custom_components" / "aesl_smart_meter"
    expected = hashlib.sha256(
        (
            (component / "api.py").read_text() + (component / "const.py").read_text()
        ).encode()
    ).hexdigest()
    assert tester.PROTOCOL_SOURCE_SHA256 == expected
    assert (
        tester.SENSOR_SOURCE_SHA256
        == hashlib.sha256((component / "sensor.py").read_bytes()).hexdigest()
    )


def test_copied_account_keeps_dataclass_validation_and_secret_repr():
    account = tester.parse_account(
        {"token": "PRIVATE-TOKEN", "caNumber": "PRIVATE-CA", "mid": 12, "phase": 3},
        "PRIVATE-CA",
    )
    assert account.meter_id == 12
    assert account.phase == 3
    assert "PRIVATE-TOKEN" not in repr(account)


def test_single_file_supports_python_310_grammar():
    ast.parse(build_standalone.TARGET.read_text(), feature_version=(3, 10))


def test_script_imports_without_home_assistant_or_repository(tmp_path):
    code = """
import importlib.abc, runpy, sys
class NoHA(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "homeassistant" or fullname.startswith("homeassistant."):
            raise RuntimeError("Standalone imported Home Assistant")
sys.meta_path.insert(0, NoHA())
script = runpy.run_path(sys.argv[1])
assert script["parse_account"]({"token":"test"}, "test").token == "test"
print("standalone OK")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(build_standalone.TARGET)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "standalone OK"


@pytest.mark.asyncio
async def test_password_test_calls_same_endpoints_with_discovered_context(
    fake_client, report, capsys
):
    await tester.check_account(None, arguments(), report)
    calls = dict((item[0], item[1:]) for item in fake_client.calls)
    assert calls["login"] == ("PRIVATE-CA", "PRIVATE-PASSWORD")
    for source in ("latest", "live", "dashboard", "mdi"):
        assert calls[source] == ("PRIVATE-CA", 97654321, 3)
    assert calls["history"] == ("PRIVATE-CA",)
    assert calls["bill"] == ("PRIVATE-CA",)
    assert tester.result_code(report) == 0
    report["result"] = "passed"
    tester.print_summary(report)
    printed = capsys.readouterr().out
    encoded = json.dumps(report)
    for secret in (
        "PRIVATE-CA",
        "PRIVATE-PASSWORD",
        "PRIVATE-TOKEN",
        "PRIVATE-CLIENT",
        "PRIVATE-METER",
        "PRIVATE-NAME",
        "PRIVATE-TIME",
        "97654321",
    ):
        assert secret not in encoded
        assert secret not in printed
    assert "value" not in report["metrics"]["import_energy"]
    assert report["metrics"]["voltage"]["source"] == "live"
    assert report["metrics"]["power_factor"]["source"] == "live"


@pytest.mark.asyncio
async def test_values_only_expose_selected_metrics(fake_client, report):
    await tester.check_account(None, arguments("--show-values"), report)
    assert report["metrics"]["import_energy"]["value"] == 123
    assert report["metrics"]["voltage"]["value"] == 230
    assert "PRIVATE-METER" not in json.dumps(report)
    assert "PRIVATE-NAME" not in json.dumps(report)


def test_three_phase_sensor_paths_match_reported_schema():
    """The account report confirms these keys; values here remain synthetic."""
    data = {
        "latest": {
            "table1": [
                {
                    "voltage": None,
                    "current": None,
                    "rCurrent": "NaN",
                    "yCurrent": None,
                    "bCurrent": None,
                }
            ]
        },
        "live": {
            "meterData": [
                {
                    "voltage": None,
                    "current": None,
                    "ir": "3.1",
                    "iy": "0",
                    "ib": "4.2",
                    "vrn": "229.1",
                    "vyn": "231.2",
                    "vbn": "232.3",
                }
            ]
        },
    }
    metrics = tester.metric_summary(data)
    for key in (
        "current_r",
        "current_y",
        "current_b",
        "voltage_rn",
        "voltage_yn",
        "voltage_bn",
    ):
        assert metrics[key]["available"]
        assert metrics[key]["source"] == "live"
        assert "value" not in metrics[key]
    assert not metrics["current"]["available"]
    assert not metrics["voltage"]["available"]
    assert tester.metric_summary(data, show_values=True)["current_y"]["value"] == 0.0


@pytest.mark.asyncio
async def test_optional_otp_reuses_credentials_without_reporting_code(
    fake_client, report, monkeypatch
):
    original = tester.private_input
    monkeypatch.setattr(
        tester,
        "private_input",
        lambda prompt, environment_name=None: (
            "012345" if environment_name is None else original(prompt, environment_name)
        ),
    )
    await tester.check_account(None, arguments("--otp"), report)
    calls = fake_client.calls
    assert ("request_otp", "PRIVATE-CA", "PRIVATE-PASSWORD") in calls
    assert ("verify_otp", "PRIVATE-CA", "PRIVATE-PASSWORD", "012345") in calls
    assert all(item[0] != "login" for item in calls)
    assert "012345" not in json.dumps(report)


@pytest.mark.asyncio
async def test_failed_login_stops_all_reading_requests(fake_client, report):
    fake_client.failure = "login"
    await tester.check_account(None, arguments(), report)
    assert [item[0] for item in fake_client.calls] == ["login"]
    assert tester.result_code(report) == 1
    assert "PRIVATE-PASSWORD" not in json.dumps(report)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,code", [("bill", 2), ("all", 1), ("expired", 1)])
async def test_endpoint_failures_get_distinct_result_codes(
    fake_client, report, failure, code
):
    fake_client.failure = failure
    await tester.check_account(None, arguments(), report)
    assert tester.result_code(report) == code


@pytest.mark.asyncio
async def test_missing_context_skips_meter_requests(fake_client, report):
    fake_client.account = tester.MahaVidyutAccount("PRIVATE-CA", "PRIVATE-TOKEN")
    await tester.check_account(None, arguments(), report)
    assert {item[0] for item in fake_client.calls} == {"login", "history", "bill"}
    for source in ("latest", "live", "dashboard", "mdi"):
        assert report["checks"][source]["status"] == "skipped"
    assert tester.result_code(report) == 2


@pytest.mark.asyncio
async def test_explicit_meter_context_overrides_missing_metadata(fake_client, report):
    fake_client.account = tester.MahaVidyutAccount("PRIVATE-CA", "PRIVATE-TOKEN")
    await tester.check_account(
        None, arguments("--meter-id", "9876", "--phase", "3"), report
    )
    assert ("latest", "PRIVATE-CA", 9876, 3) in fake_client.calls
    assert report["account_context"]["meter_id_overridden"]


@pytest.mark.asyncio
async def test_probe_never_reads_credentials(monkeypatch, report):
    calls = []

    class ProbeClient:
        def __init__(self, session):
            pass

        async def async_post(self, endpoint, body, **kwargs):
            calls.append((endpoint, body, kwargs))
            raise tester.MahaVidyutAuthenticationError("MahaVidyut session expired")

    monkeypatch.setattr(tester, "MahaVidyutClient", ProbeClient)
    monkeypatch.setattr(
        tester,
        "get_credentials",
        lambda args: pytest.fail("Probe requested credentials"),
    )
    await tester.check_probe(None, report)
    assert calls == [("Dashboard/LatestIPData", {}, {"authenticated": False})]
    assert tester.result_code(report) == 0


@pytest.mark.asyncio
async def test_trace_never_records_body_headers_or_query(report):
    config = tester.trace_config(report)
    context = SimpleNamespace()
    params = trace_parameters()
    await config.on_request_start[0](None, context, params)
    await config.on_request_headers_sent[0](None, context, params)
    await config.on_request_end[0](None, context, params)
    row = report["requests"][0]
    assert row["status"] == 200
    assert row["host"] == "cportal.aeslami-mh.com"
    assert row["accept_encoding"] == "gzip, deflate, zstd"
    assert row["content_encoding"] == "gzip"
    assert row["content_length"] == 123
    assert row["transfer_encoding"] is None
    assert row["headers_received"]
    assert not row["body_read_completed"]
    assert "body_bytes" not in row
    await config.on_response_chunk_received[0](None, context, params)
    assert row["body_read_completed"]
    assert row["body_bytes"] == len(params.chunk)
    assert row["seconds"] >= row["headers_seconds"]
    assert "PRIVATE" not in json.dumps(report)


@pytest.mark.asyncio
async def test_trace_keeps_interleaved_same_path_requests_separate(report):
    config = tester.trace_config(report)
    first, second = SimpleNamespace(), SimpleNamespace()
    first_params, second_params = trace_parameters(), trace_parameters()
    second_params.headers["Accept-Encoding"] = "identity"
    second_params.chunk = b"different-length"
    for context, params in [(first, first_params), (second, second_params)]:
        await config.on_request_start[0](None, context, params)
        await config.on_request_headers_sent[0](None, context, params)
    await config.on_request_end[0](None, second, second_params)
    await config.on_request_end[0](None, first, first_params)
    await config.on_response_chunk_received[0](None, first, first_params)
    assert report["requests"][0]["accept_encoding"] == "identity"
    assert not report["requests"][0]["body_read_completed"]
    assert report["requests"][1]["body_bytes"] == len(first_params.chunk)
    await config.on_response_chunk_received[0](None, second, second_params)
    assert report["requests"][0]["body_bytes"] == len(second_params.chunk)


@pytest.mark.asyncio
async def test_trace_uses_headers_sent_and_sanitizes_protocol_values(report):
    config = tester.trace_config(report)
    context = SimpleNamespace()
    params = trace_parameters()
    params.headers["Accept-Encoding"] = "identity"
    await config.on_request_start[0](None, context, params)
    params.headers["Accept-Encoding"] = "gzip;q=1, deflate;q=0.5"
    await config.on_request_headers_sent[0](None, context, params)
    params.response.headers.update(
        {
            "Content-Encoding": "PRIVATE-ENCODING",
            "Content-Length": "PRIVATE-LENGTH",
            "Transfer-Encoding": "chunked",
        }
    )
    await config.on_request_end[0](None, context, params)
    row = report["requests"][0]
    assert row["accept_encoding"] == "gzip;q=1, deflate;q=0.5"
    assert row["content_encoding"] == "other"
    assert row["content_length"] is None
    assert row["transfer_encoding"] == "chunked"
    assert "PRIVATE" not in json.dumps(report)


@pytest.mark.asyncio
async def test_trace_connection_failure_has_no_completed_response(report):
    config = tester.trace_config(report)
    context = SimpleNamespace()
    params = trace_parameters()
    await config.on_request_start[0](None, context, params)
    await config.on_request_exception[0](None, context, params)
    row = report["requests"][0]
    assert not row["headers_received"]
    assert not row["body_read_completed"]
    assert row["accept_encoding"] is None
    assert row["exception_chain"] == ["RuntimeError"]
    assert "PRIVATE" not in json.dumps(report)


def test_failure_summary_preserves_nested_cause_and_context_types():
    cause = ValueError("PRIVATE-PAYLOAD")
    middle = RuntimeError("PRIVATE-TRANSPORT")
    middle.__context__ = cause
    outer = tester.MahaVidyutConnectionError("MahaVidyut connection failed")
    outer.__cause__ = middle
    result = tester.failure_summary(outer)
    assert result["cause_type"] == "RuntimeError"
    assert result["exception_chain"] == [
        "MahaVidyutConnectionError",
        "RuntimeError",
        "ValueError",
    ]
    assert "PRIVATE" not in json.dumps(result)


def test_exception_type_chain_is_bounded_and_cycle_safe():
    first, second = RuntimeError("PRIVATE-A"), ValueError("PRIVATE-B")
    first.__cause__ = second
    second.__context__ = first
    assert tester.exception_type_chain(first) == [
        "RuntimeError",
        "ValueError",
    ]
    previous = first
    for _ in range(10):
        outer = RuntimeError("PRIVATE-C")
        outer.__cause__ = previous
        previous = outer
    assert len(tester.exception_type_chain(previous)) == 6


@pytest.mark.parametrize(
    ("headers", "body", "error_type"),
    [
        (b"Content-Length: 2\r\n", b"ok", None),
        (b"Content-Length: 100\r\n", b"short", "ContentLengthError"),
        (
            b"Content-Length: 7\r\nContent-Encoding: gzip\r\n",
            b"invalid",
            "ContentEncodingError",
        ),
    ],
)
async def test_actual_response_trace_distinguishes_body_failures(
    report, headers, body, error_type
):
    """Exercise aiohttp's real trace timing with a local HTTP server."""

    async def respond(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(
                b"HTTP/1.1 200 OK\r\n" + headers + b"Connection: close\r\n\r\n" + body
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(respond, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        async with tester.aiohttp.ClientSession(
            trace_configs=[tester.trace_config(report)],
            timeout=tester.aiohttp.ClientTimeout(total=5),
        ) as session:
            async with session.get(f"http://127.0.0.1:{port}/api/test") as response:
                if error_type:
                    with pytest.raises(tester.aiohttp.ClientPayloadError) as caught:
                        await response.read()
                    failure = tester.failure_summary(caught.value)
                    assert error_type in failure["exception_chain"]
                else:
                    assert await response.read() == body

    row = report["requests"][0]
    assert row["status"] == 200
    assert row["headers_received"]
    assert row["accept_encoding"] is not None
    assert row["body_read_completed"] is (error_type is None)
    if error_type:
        assert "body_bytes" not in row
    else:
        assert row["body_bytes"] == len(body)


def test_summary_does_not_call_header_only_200_a_complete_body(capsys):
    tester.print_summary(
        {
            "result": "partial",
            "checks": {},
            "requests": [
                {
                    "path": "/api/Dashboard/MeterLiveData",
                    "status": 200,
                    "seconds": 0.032,
                    "headers_received": True,
                    "body_read_completed": False,
                }
            ],
        }
    )
    assert "HTTP 200 (headers only; body not confirmed)" in capsys.readouterr().out


def test_no_cross_feed_fallback_for_energy():
    data = {"live": {"meterData": [{"kWh": 999, "kw": 1}]}}
    metrics = tester.metric_summary(data, True)
    assert not metrics["import_energy"]["available"]
    assert metrics["active_power"]["value"] == 1


def test_unexpected_error_does_not_echo_exception_payload():
    assert "PRIVATE-PASSWORD" not in json.dumps(
        tester.failure_summary(RuntimeError("PRIVATE-PASSWORD"))
    )


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "not-an-id"])
def test_invalid_mid_rejected_before_any_request(value):
    with pytest.raises(SystemExit):
        arguments("--meter-id", value)


def test_empty_sensor_responses_are_partial():
    report = {
        "checks": {"sign_in": {"status": "passed"}, "history": {"status": "passed"}},
        "metrics": {},
        "metrics_available": 0,
    }
    assert tester.result_code(report) == 2
