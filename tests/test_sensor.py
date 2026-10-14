"""Sensor value conversion and availability regressions."""

from types import SimpleNamespace

import pytest

from custom_components.aesl_smart_meter.sensor import DESCRIPTIONS, AESLSensor, lookup


def make_sensor(key, value, *, last_update_success=True):
    description = next(
        description for description in DESCRIPTIONS if description.key == key
    )
    root = value
    for part in reversed(description.path):
        if isinstance(part, int):
            root = [None] * part + [root]
        else:
            root = {part: root}
    coordinator = SimpleNamespace(
        data={description.source: root}, last_update_success=last_update_success
    )
    return AESLSensor(coordinator, "synthetic-consumer", description)


@pytest.mark.parametrize("key", ["import_energy", "power_factor", "current_balance"])
@pytest.mark.parametrize("value, expected", [(0, 0.0), ("0", 0.0), (" 12.5 ", 12.5)])
def test_numeric_values_include_unitless_measurements(key, value, expected):
    sensor = make_sensor(key, value)

    assert sensor.native_value == expected
    assert isinstance(sensor.native_value, float)
    assert sensor.available


@pytest.mark.parametrize("key", ["import_energy", "power_factor", "current_balance"])
@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        "unavailable",
        "",
        "NaN",
        "Infinity",
        "-inf",
        float("nan"),
        float("inf"),
    ],
)
def test_invalid_numeric_values_are_unavailable(key, value):
    sensor = make_sensor(key, value)

    assert sensor.native_value is None
    assert not sensor.available


def test_text_sensor_preserves_connection_status():
    sensor = make_sensor("connection_status", "Connected")

    assert sensor.native_value == "Connected"
    assert sensor.available


def test_numeric_overflow_is_unavailable():
    sensor = make_sensor("import_energy", 10**1000)

    assert sensor.native_value is None
    assert not sensor.available


def test_unitless_sensor_rejects_nonfinite_numbers():
    sensor = make_sensor("assigned_max_demand", float("nan"))

    assert sensor.native_value is None
    assert not sensor.available


def test_coordinator_failure_makes_sensor_unavailable():
    sensor = make_sensor("import_energy", 12.5, last_update_success=False)

    assert sensor.native_value == 12.5
    assert not sensor.available


def test_missing_response_path_is_unavailable():
    sensor = make_sensor("import_energy", 12.5)
    sensor.coordinator.data = {"live": {"meterData": []}}

    assert sensor.native_value is None
    assert not sensor.available


@pytest.mark.parametrize(
    "root", [{}, {"meterData": None}, {"meterData": {}}, {"meterData": []}]
)
def test_lookup_tolerates_missing_or_wrong_container_types(root):
    assert lookup(root, "meterData", 0, "kWh") is None


@pytest.mark.parametrize(
    "key, expected",
    [
        ("active_power", 0.8),
        ("voltage", 230.1),
        ("voltage_rn", 229.1),
        ("voltage_yn", 231.2),
        ("voltage_bn", 232.3),
        ("current", 3.4),
        ("current_r", 1.1),
        ("current_y", 2.2),
        ("current_b", 0.0),
        ("frequency", 50.0),
        ("power_factor", 0.95),
    ],
)
def test_live_meter_shape_supplies_fallback_readings(key, expected):
    """Exercise APK field spellings rather than constructing paths from descriptions."""
    sensor = make_sensor(key, None)
    sensor.coordinator.data = {
        "live": {
            "meterData": [
                {
                    "kWh": "1234.5",
                    "kWhExport": "6.7",
                    "kw": "0.8",
                    "voltage": "230.1",
                    "vrn": "229.1",
                    "vyn": "231.2",
                    "vbn": "232.3",
                    "current": "3.4",
                    "ir": "1.1",
                    "iy": "2.2",
                    "ib": "0",
                    "frequency": "50.0",
                    "pf": "0.95",
                    "meterReadingTime": "2026-01-01T12:00:00",
                }
            ]
        },
    }

    assert sensor.native_value == expected
    assert sensor.available
    assert sensor.extra_state_attributes == {
        "meter_reading_time": "2026-01-01T12:00:00"
    }


@pytest.mark.parametrize(
    "key, expected",
    [
        ("import_energy", 2000.0),
        ("export_energy", 20.0),
        ("active_power", 1.8),
        ("voltage", 220.1),
        ("voltage_rn", 219.1),
        ("voltage_yn", 221.2),
        ("voltage_bn", 222.3),
        ("current", 8.4),
        ("current_r", 4.1),
        ("current_y", 5.2),
        ("current_b", 0.0),
        ("frequency", 49.9),
        ("power_factor", 0.85),
    ],
)
def test_latest_primary_readings_and_timestamps_are_preferred(key, expected):
    sensor = make_sensor(key, None)
    sensor.coordinator.data = {
        "latest": {
            "table": [{"readingDate": "2026-01-01T12:15:00"}],
            "table1": [
                {
                    "kWh": "2000",
                    "kWhExport": "20",
                    "kW": "1.8",
                    "voltage": "220.1",
                    "voltage_RN": "219.1",
                    "voltage_YN": "221.2",
                    "voltage_BN": "222.3",
                    "current": "8.4",
                    "rCurrent": "4.1",
                    "yCurrent": "5.2",
                    "bCurrent": "0",
                    "frequency": "49.9",
                    "pf": "0.85",
                }
            ],
        },
        "live": {
            "meterData": [
                {
                    "kWh": "1999",
                    "kWhExport": "19",
                    "kw": "9",
                    "voltage": "9",
                    "vrn": "9",
                    "vyn": "9",
                    "vbn": "9",
                    "current": "9",
                    "ir": "9",
                    "iy": "9",
                    "ib": "9",
                    "frequency": "9",
                    "pf": "0.9",
                    "meterReadingTime": "2026-01-01T12:00:00",
                }
            ]
        },
    }

    assert sensor.native_value == expected
    assert sensor.extra_state_attributes == {
        "meter_reading_time": "2026-01-01T12:15:00"
    }


@pytest.mark.parametrize("invalid_primary", [None, "not a reading", "NaN"])
def test_missing_or_invalid_primary_reading_uses_live_value_and_timestamp(
    invalid_primary,
):
    sensor = make_sensor("active_power", None)
    sensor.coordinator.data = {
        "latest": {
            "table": [{"readingDate": "2026-01-01T12:15:00"}],
            "table1": [{"kW": invalid_primary}],
        },
        "live": {
            "meterData": [{"kw": "1.5", "meterReadingTime": "2026-01-01T12:00:00"}]
        },
    }

    assert sensor.native_value == 1.5
    assert sensor.available
    assert sensor.extra_state_attributes == {
        "meter_reading_time": "2026-01-01T12:00:00"
    }


@pytest.mark.parametrize("invalid_primary", [None, "NaN", "not a reading"])
def test_three_phase_readings_work_without_generic_voltage_or_current(invalid_primary):
    """Use the real report's field names with synthetic readings and timestamps."""
    data = {
        "latest": {
            "table1": [
                {
                    "voltage": None,
                    "current": None,
                    "rCurrent": invalid_primary,
                    "yCurrent": invalid_primary,
                    "bCurrent": invalid_primary,
                }
            ],
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
                    "meterReadingTime": "2026-01-01T12:00:00",
                }
            ],
        },
    }
    for key, expected in (
        ("current_r", 3.1),
        ("current_y", 0.0),
        ("current_b", 4.2),
        ("voltage_rn", 229.1),
        ("voltage_yn", 231.2),
        ("voltage_bn", 232.3),
    ):
        sensor = make_sensor(key, None)
        sensor.coordinator.data = data
        assert sensor.native_value == expected
        assert sensor.available
        assert sensor.extra_state_attributes == {
            "meter_reading_time": "2026-01-01T12:00:00"
        }

    for key in ("voltage", "current"):
        sensor = make_sensor(key, None)
        sensor.coordinator.data = data
        assert sensor.native_value is None
        assert not sensor.available


@pytest.mark.parametrize(
    "key, field", [("import_energy", "kWh"), ("export_energy", "kWhExport")]
)
def test_cumulative_energy_does_not_switch_to_older_live_register(key, field):
    """A lower fallback register would look like a reset in HA energy statistics."""
    sensor = make_sensor(key, None)
    sensor.coordinator.data = {
        "latest": {
            "table": [{"readingDate": "2026-01-01T12:15:00"}],
            "table1": [{field: 2000.0}],
        },
        "live": {
            "meterData": [{field: 1999.0, "meterReadingTime": "2026-01-01T12:00:00"}]
        },
    }
    assert sensor.native_value == 2000.0
    assert sensor.available

    # The coordinator removes a source when that request fails.
    sensor.coordinator.data.pop("latest")
    assert sensor.native_value is None
    assert not sensor.available
    assert sensor.extra_state_attributes is None

    sensor.coordinator.data["latest"] = {
        "table": [{"readingDate": "2026-01-01T12:30:00"}],
        "table1": [{field: 2001.0}],
    }
    assert sensor.native_value == 2001.0
    assert sensor.available
    assert sensor.extra_state_attributes == {
        "meter_reading_time": "2026-01-01T12:30:00"
    }
