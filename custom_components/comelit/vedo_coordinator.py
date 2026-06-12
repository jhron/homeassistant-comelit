"""Coordinator for Comelit Vedo HTTP polling."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
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

# Consecutive update cycles lost to auth errors before starting reauth.
MAX_AUTH_FAILURES = 3

# The panel registers a fresh session asynchronously; a LAN request sent
# right after login can outrun it and get "logged": 0 (verified on a real
# panel - sessions also expire 120 s after login regardless of activity).
RETRY_DELAY = 1.0


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
        self._auth_failures = 0
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
                    self._auth_failures = 0
                    return data
        except ComelitAuthError as err:
            # The panel under load reports "logged": 0 even for valid
            # sessions, so only repeated consecutive failures mean the
            # credentials are actually wrong.
            self._auth_failures += 1
            if self._auth_failures >= MAX_AUTH_FAILURES:
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN,
                    translation_key="cannot_authenticate",
                ) from err
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": repr(err)},
            ) from err
        except ComelitConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": repr(err)},
            ) from err

    async def async_disconnect(self) -> None:
        """Disconnect the wrapped Vedo API."""
        await self.api.async_disconnect()
