"""Platform for cover integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_CLOSED, STATE_OPENING, STATE_CLOSING
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .comelit_device import ComelitDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Comelit covers."""
    hub = hass.data[DOMAIN][entry.entry_id]
    hub.cover_add_entities = async_add_entities
    _LOGGER.info("Comelit Cover Integration started")


class ComelitCover(ComelitDevice, CoverEntity):
    """Representation of a Comelit cover."""

    def __init__(
        self,
        id: str,
        description: str,
        closed: str,
        position: int,
        hub,
    ) -> None:
        """Initialize the cover."""
        ComelitDevice.__init__(self, id, None, description)
        self._state = closed
        self._hub = hub

        if position != -1:
            self._position = position
        else:
            self._position = None

        # Set supported features based on position availability
        self._attr_supported_features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
        )
        if position != -1:
            self._attr_supported_features |= CoverEntityFeature.SET_POSITION

    @property
    def device_class(self) -> CoverDeviceClass:
        """Return the device class of the cover."""
        return CoverDeviceClass.SHUTTER

    @property
    def is_closed(self) -> bool:
        """Return if the cover is closed."""
        return self._state == STATE_CLOSED

    @property
    def is_opening(self) -> bool:
        """Return if the cover is opening."""
        return self._state == STATE_OPENING

    @property
    def is_closing(self) -> bool:
        """Return if the cover is closing."""
        return self._state == STATE_CLOSING

    @property
    def current_cover_position(self) -> int | None:
        """Return current position of cover (0-100)."""
        if self._position is None:
            return None
        return 100 - self._position

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set cover position."""
        position = kwargs.get("position")
        if position is not None:
            _LOGGER.debug("Setting position %s for cover %s", position, self.name)
            await self._hub.async_cover_position(self._id, 100 - position)

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        _LOGGER.debug("Opening cover %s", self.name)
        await self._hub.async_cover_up(self._id)
        self._state = STATE_OPENING
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        _LOGGER.debug("Closing cover %s", self.name)
        await self._hub.async_cover_down(self._id)
        self._state = STATE_CLOSING
        self.async_write_ha_state()

    def update_state(self, state: str, position: int) -> None:
        """Update cover state from hub."""
        old_state = self._state
        old_position = self._position

        self._state = state
        if position != -1:
            self._position = position

        if old_state != state or old_position != position:
            self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        _LOGGER.debug("Stopping cover %s, is_opening=%s, is_closing=%s", 
                      self.name, self.is_opening, self.is_closing)
        if self.is_opening:
            await self._hub.async_cover_down(self._id)
        elif self.is_closing:
            await self._hub.async_cover_up(self._id)
