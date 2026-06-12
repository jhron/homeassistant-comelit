"""Coordinator for Comelit Vedo HTTP polling."""
from __future__ import annotations

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
                    return await self.api.get_all_areas_and_zones()
                except ComelitAuthError:
                    # Session cookie expired - log in again and retry once.
                    if attempt == 2:
                        raise
                    await self.api.login()
                except ComelitConnectionError:
                    # The panel's web server is slow under load - retry once
                    # before failing the update.
                    if attempt == 2:
                        raise
        except ComelitAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_authenticate",
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
