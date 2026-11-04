"""Check energy metadata against Home Assistant's Energy and recorder rules."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
import pytest_asyncio
from homeassistant.components.energy import validate as energy_validate
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.components.sensor import recorder as sensor_recorder
from homeassistant.components.sensor.const import DEVICE_CLASS_STATE_CLASSES
from homeassistant.components.sensor.recorder import (
    _get_sensor_states,
    _wanted_statistics,
    reset_detected,
)
from homeassistant.core import HomeAssistant

from custom_components.aesl_smart_meter.sensor import DESCRIPTIONS, MahaVidyutSensor

ENTITY_ID = "sensor.aesl_smart_meter_energy_consumed_today"


@pytest_asyncio.fixture
async def hass(tmp_path):
    instance = HomeAssistant(str(tmp_path))
    yield instance
    await instance.async_stop()


def make_sensor(key, *, legacy=False):
    description = next(item for item in DESCRIPTIONS if item.key == key)
    if legacy:
        description = replace(description, state_class=SensorStateClass.MEASUREMENT)
    coordinator = SimpleNamespace(
        data={
            "history": {"totalAvgConsumptionToday": [{"total_kwh_imp": 9.5}]},
            "dashboard": {"forecast": {"currentMonth": {"value": 300}}},
            "bill": {"data": {"consumption": 250}},
        },
        last_update_success=True,
    )
    return MahaVidyutSensor(coordinator, "synthetic-consumer", description)


def write_state(hass, sensor):
    attributes = {
        "device_class": sensor.device_class,
        "unit_of_measurement": sensor.native_unit_of_measurement,
    }
    if sensor.state_class is not None:
        attributes["state_class"] = sensor.state_class
    hass.states.async_set(ENTITY_ID, str(sensor.native_value), attributes)
    return hass.states.get(ENTITY_ID)


@pytest.mark.parametrize("legacy", [True, False])
async def test_daily_energy_dashboard_validation(hass, monkeypatch, legacy):
    """Reproduce the reported warning and validate the fixed entity metadata."""
    sensor = make_sensor("today_consumption", legacy=legacy)
    state = write_state(hass, sensor)
    monkeypatch.setattr(energy_validate.recorder, "is_entity_recorded", lambda *_: True)
    issues = energy_validate.ValidationIssues()

    energy_validate._async_validate_usage_stat(
        hass,
        {ENTITY_ID: (1, {})},
        ENTITY_ID,
        energy_validate.ENERGY_USAGE_DEVICE_CLASSES,
        energy_validate.ENERGY_USAGE_UNITS,
        energy_validate.ENERGY_UNIT_ERROR,
        issues,
    )

    expected = {"entity_state_class_measurement_no_last_reset"} if legacy else set()
    assert set(issues.issues) == expected
    assert "last_reset" not in state.attributes
    assert sensor.unique_id == "synthetic-consumer_today_consumption"
    if not legacy:
        assert _wanted_statistics([state])[ENTITY_ID].types == {"sum"}


@pytest.mark.parametrize("first_reading", [0, 0.25])
async def test_daily_counter_reset_is_detected_without_last_reset(hass, first_reading):
    sensor = make_sensor("today_consumption")
    previous = sensor.native_value
    sensor.coordinator.data["history"] = {
        "totalAvgConsumptionToday": [{"total_kwh_imp": first_reading}]
    }
    state = write_state(hass, sensor)

    assert sensor.state_class == SensorStateClass.TOTAL_INCREASING
    assert sensor.available
    assert sensor.native_value == first_reading
    assert reset_detected(hass, ENTITY_ID, sensor.native_value, previous, state)
    assert "last_reset" not in state.attributes


@pytest.mark.parametrize("key", ["current_month_forecast", "recent_bill_consumption"])
async def test_forecast_and_bill_are_display_values_not_usage_counters(
    hass, monkeypatch, key
):
    sensor = make_sensor(key)
    write_state(hass, sensor)

    assert sensor.available
    assert sensor.native_value in (250, 300)
    assert sensor.device_class == SensorDeviceClass.ENERGY
    assert sensor.native_unit_of_measurement == "kWh"
    assert sensor.state_class is None
    monkeypatch.setattr(
        sensor_recorder, "get_instance", lambda _: SimpleNamespace(entity_filter=None)
    )
    recorded_states = await hass.async_add_executor_job(_get_sensor_states, hass)
    assert ENTITY_ID not in {state.entity_id for state in recorded_states}


def test_energy_state_classes_follow_home_assistant_rules():
    for description in DESCRIPTIONS:
        if description.device_class == SensorDeviceClass.ENERGY:
            assert (
                description.state_class is None
                or description.state_class
                in (DEVICE_CLASS_STATE_CLASSES[SensorDeviceClass.ENERGY])
            )
