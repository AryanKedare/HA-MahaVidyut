"""Periodic coordinator for AESL Smart Meter readings."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AESLClient, AESLError
from .const import CONF_LOGIN_ID, CONF_METER_ID, CONF_PHASE, DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class AESLDataCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Gather independent endpoint responses; tolerate optional endpoint failures."""

    def __init__(self, hass, client: AESLClient, config: dict[str, Any]):
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.client = client
        self.login_id = str(config[CONF_LOGIN_ID]).strip()
        self.meter_id = int(config.get(CONF_METER_ID, 0))
        self.phase = int(config.get(CONF_PHASE, 1))
        self._cache: dict[str, dict[str, Any]] = {}
        self._last_slow: datetime | None = None

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = dict(self._cache)
        jobs = {
            "history": self.client.async_get_log_history(self.login_id),
            "latest": self.client.async_get_latest(),
        }
        if self.meter_id:
            jobs["dashboard"] = self.client.async_get_dashboard(
                self.login_id, self.meter_id, self.phase
            )
        now = datetime.now(timezone.utc)
        slow_due = self._last_slow is None or now - self._last_slow >= timedelta(hours=12)
        if slow_due:
            jobs["bill"] = self.client.async_get_recent_bill(self.login_id)
            if self.meter_id:
                jobs["mdi"] = self.client.async_get_mdi(
                    self.login_id, self.meter_id, self.phase
                )

        # Keep each endpoint isolated: a 500 from MeterLiveData (observed in
        # the HAR) must not take down the history and energy sensors.
        success = 0
        for name, job in jobs.items():
            try:
                results[name] = await job
                success += 1
            except AESLError as exc:
                _LOGGER.debug("AESL %s unavailable: %s", name, exc)
                results.pop(name, None)

        if slow_due:
            self._last_slow = now
        if success == 0:
            raise UpdateFailed("Unable to retrieve AESL smart meter readings")
        self._cache = results
        return results
