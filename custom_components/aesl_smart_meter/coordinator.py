"""Periodic coordinator for AESL Smart Meter readings."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AESLAuthenticationError, AESLClient, AESLError
from .const import CONF_LOGIN_ID, CONF_METER_ID, CONF_PHASE, DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class AESLDataCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Gather independent endpoint responses; tolerate optional endpoint failures."""

    def __init__(
        self,
        hass,
        client: AESLClient,
        config: dict[str, Any],
        *,
        config_entry: ConfigEntry | None = None,
    ):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            config_entry=config_entry,
        )
        self.client = client
        self.login_id = str(config[CONF_LOGIN_ID]).strip()
        self.meter_id = int(config.get(CONF_METER_ID, 0))
        self.phase = int(config.get(CONF_PHASE, 1))
        self._cache: dict[str, dict[str, Any]] = {}
        self._last_slow_success: dict[str, datetime] = {}

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = dict(self._cache)
        jobs = {
            "history": self.client.async_get_log_history(self.login_id),
            "latest": self.client.async_get_latest(
                self.login_id, self.meter_id, self.phase
            ),
        }
        if self.meter_id:
            jobs["dashboard"] = self.client.async_get_dashboard(
                self.login_id, self.meter_id, self.phase
            )
            jobs["live"] = self.client.async_get_live(
                self.login_id, self.meter_id, self.phase
            )
        now = datetime.now(UTC)

        def slow_due(source: str) -> bool:
            last_success = self._last_slow_success.get(source)
            return last_success is None or now - last_success >= timedelta(hours=12)

        if slow_due("bill"):
            jobs["bill"] = self.client.async_get_recent_bill(self.login_id)
        if self.meter_id and slow_due("mdi"):
            jobs["mdi"] = self.client.async_get_mdi(
                self.login_id, self.meter_id, self.phase
            )

        # Concurrent requests keep a failed optional endpoint from delaying
        # every other reading. Cancelling the refresh also cancels its requests.
        responses = await asyncio.gather(*jobs.values(), return_exceptions=True)
        for response in responses:
            if isinstance(response, AESLAuthenticationError):
                raise ConfigEntryAuthFailed("AESL authentication expired") from response

        success = 0
        for name, response in zip(jobs, responses, strict=True):
            if isinstance(response, AESLError):
                _LOGGER.debug("AESL %s unavailable: %s", name, response)
                results.pop(name, None)
                continue
            if isinstance(response, BaseException):
                raise response
            results[name] = response
            success += 1
            if name in ("bill", "mdi"):
                self._last_slow_success[name] = now

        if success == 0:
            raise UpdateFailed("Unable to retrieve AESL smart meter readings")
        self._cache = results
        return results
