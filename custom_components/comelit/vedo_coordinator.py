"""Coordinator for Comelit Vedo HTTP polling."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import time
from typing import Any, Mapping

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .exception import ComelitAuthError, ComelitConnectionError

_LOGGER = logging.getLogger(__name__)

ALARM_ZONE = "alarm_zone"
ALARM_AREA = "alarm_area"

# How long auth errors must persist before starting reauth. A reauth stops
# polling until the user reconfigures the entry, so a panel that refuses valid
# sessions for a while (2026-11-10: ~90 s with the correct PIN) must not trigger
# it; wrong credentials still end in reauth after this time.
AUTH_FAILURE_GRACE = 30 * 60  # seconds

# Start of the current auth outage per config entry. Kept outside the
# coordinator because a failing first refresh makes HA retry the setup with a
# new coordinator each time; the clock must survive those retries.
_AUTH_FAILING_SINCE: dict[str, float] = {}

# The panel registers a fresh session asynchronously; a LAN request sent
# right after login can outrun it and get "logged": 0 (verified on a real
# panel - sessions also expire 120 s after login regardless of activity).
RETRY_DELAY = 1.0

# Failed cycles bridged with the last snapshot before going unavailable.
MAX_STALE_CYCLES = 5


class ComelitVedoCoordinator(DataUpdateCoordinator[dict[str, Mapping[int, Any]]]):
    """Coordinator for Comelit Vedo HTTP polling."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: Any,
        entry: ConfigEntry,
        scan_interval: int,
    ) -> None:
        """Initialize the coordinator."""
        self.api = api
        self._entry_id = entry.entry_id
        self._failed_cycles = 0
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}-{entry.entry_id}-vedo",
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Mapping[int, Any]]:
        """Fetch complete Vedo data."""
        try:
            for attempt in (1, 2):
                try:
                    if not self.api.authenticated:
                        await self.api.login()
                    data = await self.api.get_all_areas_and_zones()
                except ComelitAuthError:
                    # Session cookie expired - log in again and retry once,
                    # giving the panel a moment to register the new session.
                    if attempt == 2:
                        raise
                    await self.api.login()
                    await asyncio.sleep(RETRY_DELAY)
                except ComelitConnectionError:
                    # The panel's web server is slow under load - retry once
                    # before failing the update.
                    if attempt == 2:
                        raise
                    await asyncio.sleep(RETRY_DELAY)
                else:
                    since = _AUTH_FAILING_SINCE.pop(self._entry_id, None)
                    if since is not None:
                        _LOGGER.warning(
                            "Vedo accepts the session again after %.0f s of auth errors",
                            time.monotonic() - since,
                        )
                    self._failed_cycles = 0
                    return self._bridge_empty_sections(data)
        except ComelitAuthError as err:
            # The panel under load reports "logged": 0 even for valid
            # sessions, so only auth errors lasting the whole grace period
            # mean the credentials are actually wrong.
            now = time.monotonic()
            since = _AUTH_FAILING_SINCE.get(self._entry_id)
            if since is None:
                _AUTH_FAILING_SINCE[self._entry_id] = now
                _LOGGER.warning(
                    "Vedo refused the session, reauth only if this persists %d min: %s",
                    AUTH_FAILURE_GRACE // 60,
                    err,
                )
            elif now - since >= AUTH_FAILURE_GRACE:
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN,
                    translation_key="cannot_authenticate",
                ) from err
            return self._stale_or_fail(err)
        except ComelitConnectionError as err:
            return self._stale_or_fail(err)

    def _bridge_empty_sections(
        self, data: dict[str, Mapping[int, Any]]
    ) -> dict[str, Mapping[int, Any]]:
        """Reuse the last non-empty zone/area section.

        The panel periodically answers with valid JSON but empty content
        while it refreshes internally; without bridging, every entity of the
        affected section flaps to unavailable for that one cycle.
        """
        previous = self.data or {}
        for section in (ALARM_ZONE, ALARM_AREA):
            if not data.get(section) and previous.get(section):
                _LOGGER.debug(
                    "Vedo returned an empty %s section, reusing last snapshot",
                    section,
                )
                data[section] = previous[section]
        return data

    def _stale_or_fail(self, err: Exception) -> dict[str, Mapping[int, Any]]:
        """Bridge brief panel hiccups with the last snapshot."""
        self._failed_cycles += 1
        if self.data and self._failed_cycles <= MAX_STALE_CYCLES:
            _LOGGER.debug(
                "Vedo update failed (%r), reusing last snapshot (%s/%s)",
                err,
                self._failed_cycles,
                MAX_STALE_CYCLES,
            )
            return self.data
        raise UpdateFailed(
            translation_domain=DOMAIN,
            translation_key="update_failed",
            translation_placeholders={"error": repr(err)},
        ) from err

    async def async_disconnect(self) -> None:
        """Disconnect the wrapped Vedo API."""
        await self.api.async_disconnect()
