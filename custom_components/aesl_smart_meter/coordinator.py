"""Periodic coordinator for MahaVidyut readings."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MahaVidyutAuthenticationError, MahaVidyutClient, MahaVidyutError
from .const import (
    CONF_AUTO_REAUTH,
    CONF_CLIENT_ID,
    CONF_LOGIN_ID,
    CONF_METER_ID,
    CONF_PHASE,
    CONF_TOKEN,
    CONF_USE_OTP,
    NAME,
    SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class MahaVidyutDataCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Gather independent endpoint responses; tolerate optional endpoint failures."""

    def __init__(
        self,
        hass,
        client: MahaVidyutClient,
        config: dict[str, Any],
        *,
        config_entry: ConfigEntry | None = None,
    ):
        super().__init__(
            hass,
            _LOGGER,
            name=NAME,
            update_interval=SCAN_INTERVAL,
            config_entry=config_entry,
        )
        self.client = client
        self.login_id = str(config[CONF_LOGIN_ID]).strip()
        self.meter_id = int(config.get(CONF_METER_ID, 0))
        self.phase = int(config.get(CONF_PHASE, 1))
        self._password = (
            config.get(CONF_PASSWORD)
            if config.get(CONF_AUTO_REAUTH) and not config.get(CONF_USE_OTP)
            else None
        )
        self._cache: dict[str, dict[str, Any]] = {}
        self._last_slow_success: dict[str, datetime] = {}

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Recover an expired session once, when password storage was enabled."""
        try:
            return await self._async_fetch_data()
        except MahaVidyutAuthenticationError as exc:
            if not self._password:
                raise ConfigEntryAuthFailed(
                    "MahaVidyut authentication expired"
                ) from exc

        _LOGGER.debug("MahaVidyut session rejected; attempting automatic sign-in")
        try:
            account = await self.client.async_login(self.login_id, self._password)
        except MahaVidyutAuthenticationError as exc:
            raise ConfigEntryAuthFailed(
                "MahaVidyut automatic sign-in rejected"
            ) from exc
        except MahaVidyutError as exc:
            raise UpdateFailed("Unable to renew the MahaVidyut session") from exc

        self.client.set_account(account)
        self.meter_id = account.meter_id or self.meter_id
        self.phase = account.phase or self.phase
        # A new session can return different meter context. Refresh all sources.
        self._cache.clear()
        self._last_slow_success.clear()
        if self.config_entry is not None:
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **self.config_entry.data,
                    CONF_TOKEN: account.token,
                    CONF_CLIENT_ID: account.client_id,
                    CONF_METER_ID: self.meter_id,
                    CONF_PHASE: self.phase,
                },
            )
        try:
            return await self._async_fetch_data()
        except MahaVidyutAuthenticationError as exc:
            raise ConfigEntryAuthFailed("MahaVidyut authentication expired") from exc

    async def _async_fetch_data(self) -> dict[str, dict[str, Any]]:
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
        for name, response in zip(jobs, responses, strict=True):
            if isinstance(response, MahaVidyutAuthenticationError):
                _LOGGER.debug("MahaVidyut %s rejected the session", name)
                raise response

        success = 0
        for name, response in zip(jobs, responses, strict=True):
            if isinstance(response, MahaVidyutError):
                _LOGGER.debug("MahaVidyut %s unavailable: %s", name, response)
                results.pop(name, None)
                continue
            if isinstance(response, BaseException):
                raise response
            results[name] = response
            success += 1
            if name in ("bill", "mdi"):
                self._last_slow_success[name] = now

        if success == 0:
            raise UpdateFailed("Unable to retrieve MahaVidyut readings")
        self._cache = results
        return results
