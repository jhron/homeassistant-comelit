"""Platform for switch integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
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
    """Set up Comelit switches."""
    hub = hass.data[DOMAIN][entry.entry_id]
    hub.switch_add_entities = async_add_entities
    _LOGGER.info("Comelit Switch Integration started")


class ComelitSwitch(ComelitDevice, SwitchEntity):
    """Representation of a Comelit switch."""

    def __init__(
        self,
        id: str,
        description: str,
        icon: str | None,
        hub,
    ) -> None:
        """Initialize the switch."""
        self._hub = hub
        self._icon = icon
        ComelitDevice.__init__(self, id, None, description)

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self._state == STATE_ON

    @property
    def icon(self) -> str | None:
        """Return the icon of the switch."""
        return self._icon

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch."""
        await self._hub.async_switch_on(self._id)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch."""
        await self._hub.async_switch_off(self._id)


class ComelitOther(ComelitSwitch):
    """Representation of a Comelit other device as switch."""

    def __init__(self, id: str, description: str, hub) -> None:
        """Initialize the other device."""
        ComelitSwitch.__init__(self, id, description, None, hub)
