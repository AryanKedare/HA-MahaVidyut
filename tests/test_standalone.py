"""Standalone tester parity, credential handling and failure regressions."""

import ast
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

    async def async_login(self, consumer, password):
        self.calls.append(("login", consumer, password))
        if self.failure == "login":
            raise tester.AESLAuthenticationError("MahaVidyut sign-in rejected")
        return self.account

    async def async_request_otp(self, consumer, password):
        self.calls.append(("request_otp", consumer, password))

    async def async_verify_otp(self, consumer, password, otp):
        self.calls.append(("verify_otp", consumer, password, otp))
        return self.account

    async def response(self, source, args, data):
        self.calls.append((source, *args))
        if self.failure in (source, "all"):
            raise tester.AESLConnectionError("MahaVidyut POST returned HTTP 500")
        if self.failure == "expired" and source == "live":
            raise tester.AESLAuthenticationError("MahaVidyut session expired")
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
    FakeClient.account = tester.AESLAccount(
        "PRIVATE-CA", "PRIVATE-TOKEN", 97654321, 3, "PRIVATE-CLIENT"
    )
    monkeypatch.setattr(tester, "AESLClient", FakeClient)
    monkeypatch.setenv("MAHA_VIDYUT_CONSUMER", "PRIVATE-CA")
    monkeypatch.setenv("MAHA_VIDYUT_PASSWORD", "PRIVATE-PASSWORD")
    return FakeClient


@pytest.fixture
def report():
    return {"checks": {}, "requests": []}


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
    fake_client.account = tester.AESLAccount("PRIVATE-CA", "PRIVATE-TOKEN")
    await tester.check_account(None, arguments(), report)
    assert {item[0] for item in fake_client.calls} == {"login", "history", "bill"}
    for source in ("latest", "live", "dashboard", "mdi"):
        assert report["checks"][source]["status"] == "skipped"
    assert tester.result_code(report) == 2


@pytest.mark.asyncio
async def test_explicit_meter_context_overrides_missing_metadata(fake_client, report):
    fake_client.account = tester.AESLAccount("PRIVATE-CA", "PRIVATE-TOKEN")
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
            raise tester.AESLAuthenticationError("MahaVidyut session expired")

    monkeypatch.setattr(tester, "AESLClient", ProbeClient)
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
    params = SimpleNamespace(
        url=SimpleNamespace(path="/api/Account/Login", query="PRIVATE-QUERY"),
        headers={"Authorization": "PRIVATE-TOKEN"},
        body="PRIVATE-PASSWORD",
        response=SimpleNamespace(status=200),
    )
    await config.on_request_start[0](None, context, params)
    await config.on_request_end[0](None, context, params)
    encoded = json.dumps(report)
    assert report["requests"][0]["status"] == 200
    assert "PRIVATE" not in encoded


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
