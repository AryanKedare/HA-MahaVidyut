"""Read-only electricity and billing sensors for AESL Smart Meter."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_LOGIN_ID, DOMAIN, NAME
from .coordinator import AESLDataCoordinator


def lookup(root: Any, *path: str | int) -> Any:
    """Traverse nested portal response objects without throwing for missing values."""
    value = root
    for part in path:
        if isinstance(part, int):
            if not isinstance(value, list) or len(value) <= part:
                return None
            value = value[part]
        elif isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


@dataclass(frozen=True, kw_only=True)
class AESLSensorDescription(SensorEntityDescription):
    path: tuple[str | int, ...]
    source: str
    fallback_source: str | None = None
    fallback_path: tuple[str | int, ...] = ()


DESCRIPTIONS: tuple[AESLSensorDescription, ...] = (
    # An older cumulative reading from another feed would appear as a meter reset.
    AESLSensorDescription(
        key="import_energy",
        name="Imported energy",
        source="latest",
        path=("table1", 0, "kWh"),
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    AESLSensorDescription(
        key="export_energy",
        name="Exported energy",
        source="latest",
        path=("table1", 0, "kWhExport"),
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    AESLSensorDescription(
        key="active_power",
        name="Active power",
        source="latest",
        path=("table1", 0, "kW"),
        fallback_source="live",
        fallback_path=("meterData", 0, "kw"),
        native_unit_of_measurement="kW",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AESLSensorDescription(
        key="voltage",
        name="Voltage",
        source="latest",
        path=("table1", 0, "voltage"),
        fallback_source="live",
        fallback_path=("meterData", 0, "voltage"),
        native_unit_of_measurement="V",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AESLSensorDescription(
        key="voltage_rn",
        name="R-N voltage",
        source="latest",
        path=("table1", 0, "voltage_RN"),
        fallback_source="live",
        fallback_path=("meterData", 0, "vrn"),
        native_unit_of_measurement="V",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AESLSensorDescription(
        key="voltage_yn",
        name="Y-N voltage",
        source="latest",
        path=("table1", 0, "voltage_YN"),
        fallback_source="live",
        fallback_path=("meterData", 0, "vyn"),
        native_unit_of_measurement="V",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AESLSensorDescription(
        key="voltage_bn",
        name="B-N voltage",
        source="latest",
        path=("table1", 0, "voltage_BN"),
        fallback_source="live",
        fallback_path=("meterData", 0, "vbn"),
        native_unit_of_measurement="V",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AESLSensorDescription(
        key="current",
        name="Current",
        source="latest",
        path=("table1", 0, "current"),
        fallback_source="live",
        fallback_path=("meterData", 0, "current"),
        native_unit_of_measurement="A",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AESLSensorDescription(
        key="frequency",
        name="Frequency",
        source="latest",
        path=("table1", 0, "frequency"),
        fallback_source="live",
        fallback_path=("meterData", 0, "frequency"),
        native_unit_of_measurement="Hz",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AESLSensorDescription(
        key="power_factor",
        name="Power factor",
        source="latest",
        path=("table1", 0, "pf"),
        fallback_source="live",
        fallback_path=("meterData", 0, "pf"),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AESLSensorDescription(
        key="today_consumption",
        name="Energy consumed today",
        source="history",
        path=("totalAvgConsumptionToday", 0, "total_kwh_imp"),
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AESLSensorDescription(
        key="current_balance",
        name="Current balance",
        source="dashboard",
        path=("balanceDetails", "currentBalance"),
        native_unit_of_measurement="INR",
        device_class=SensorDeviceClass.MONETARY,
    ),
    AESLSensorDescription(
        key="connection_status",
        name="Connection status",
        source="dashboard",
        path=("balanceDetails", "connection_status"),
    ),
    AESLSensorDescription(
        key="current_month_forecast",
        name="Current month forecast",
        source="dashboard",
        path=("forecast", "currentMonth", "value"),
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AESLSensorDescription(
        key="assigned_max_demand",
        name="Assigned maximum demand",
        source="mdi",
        path=("assignedMaxDemand",),
    ),
    AESLSensorDescription(
        key="recent_bill_amount",
        name="Recent bill amount",
        source="bill",
        path=("data", "billAmount"),
        native_unit_of_measurement="INR",
        device_class=SensorDeviceClass.MONETARY,
    ),
    AESLSensorDescription(
        key="recent_bill_consumption",
        name="Recent billed consumption",
        source="bill",
        path=("data", "consumption"),
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    """Create sensor entities for the consumer."""
    coordinator: AESLDataCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AESLSensor(coordinator, entry.data[CONF_LOGIN_ID], description)
        for description in DESCRIPTIONS
    )


class AESLSensor(CoordinatorEntity[AESLDataCoordinator], SensorEntity):
    """One metric from a nested response field."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AESLDataCoordinator,
        login_id: str,
        description: AESLSensorDescription,
    ):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{login_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, login_id)},
            name=NAME,
            manufacturer="Adani Energy Solutions (unofficial cloud integration)",
            model="AESL Smart Meter",
        )

    @property
    def native_value(self):
        reading = self._value_and_source()
        return reading[0] if reading is not None else None

    def _value_and_source(self) -> tuple[Any, str] | None:
        """Choose the primary reading, with optional fallback for measurements."""
        description = self.entity_description
        paths = [(description.source, description.path)]
        if description.fallback_source:
            paths.append((description.fallback_source, description.fallback_path))
        for source, path in paths:
            data = (self.coordinator.data or {}).get(source, {})
            value = self._normalize_value(lookup(data, *path))
            if value is not None:
                return value, source
        return None

    def _normalize_value(self, value: Any) -> Any:
        """Prevent malformed or nonfinite values from becoming sensor states."""
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float, str)):
            if (
                self.entity_description.native_unit_of_measurement
                or self.entity_description.state_class
            ):
                try:
                    number = float(value)
                except (TypeError, ValueError, OverflowError):
                    return None
                return number if isfinite(number) else None
            if isinstance(value, float) and not isfinite(value):
                return None
            return value
        return None

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    @property
    def extra_state_attributes(self):
        reading = self._value_and_source()
        if reading is None:
            return None
        source = reading[1]
        if source == "latest":
            timestamp = lookup(
                (self.coordinator.data or {}).get("latest", {}),
                "table",
                0,
                "readingDate",
            )
        elif source == "live":
            timestamp = lookup(
                (self.coordinator.data or {}).get("live", {}),
                "meterData",
                0,
                "meterReadingTime",
            )
        else:
            return None
        if timestamp:
            return {"meter_reading_time": timestamp}
        return None
