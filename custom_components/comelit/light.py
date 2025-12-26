"""Platform for light integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_OFF
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
    """Set up Comelit lights."""
    hub = hass.data[DOMAIN][entry.entry_id]
    hub.light_add_entities = async_add_entities
    _LOGGER.info("Comelit Light Integration started")


class ComelitLight(ComelitDevice, LightEntity):
    """Representation of a Comelit light."""

    def __init__(
        self,
        id: str,
        description: str,
        state: str,
        brightness: int | None,
        hub,
    ) -> None:
        """Initialize the light."""
        ComelitDevice.__init__(self, id, None, description)
        self._hub = hub
        self._state = state
        self._brightness = brightness

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._state == STATE_ON

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Return supported color modes."""
        if self._brightness is not None:
            return {ColorMode.BRIGHTNESS}
        return {ColorMode.ONOFF}

    @property
    def color_mode(self) -> ColorMode:
        """Return the current color mode."""
        if self._brightness is not None:
            return ColorMode.BRIGHTNESS
        return ColorMode.ONOFF

    @property
    def brightness(self) -> int | None:
        """Return the brightness of the light."""
        return self._brightness

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        if brightness is not None:
            self._brightness = brightness

        await self._hub.async_light_on(self._id, self._brightness)
        self._state = STATE_ON
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        await self._hub.async_light_off(self._id)
        self._state = STATE_OFF
        self.async_write_ha_state()
