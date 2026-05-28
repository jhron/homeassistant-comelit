"""Platform for scene integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .comelit_device import ComelitDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Comelit scenes."""
    hub = entry.runtime_data
    hub.scene_add_entities = async_add_entities
    _LOGGER.debug("Comelit Scene Integration started")


class ComelitScenario(ComelitDevice, Scene):
    """Representation of a Comelit scenario."""

    def __init__(self, id: str, description: str, hub) -> None:
        """Initialize the scenario."""
        self._hub = hub
        ComelitDevice.__init__(
            self,
            id,
            None,
            description,
            device_id=id,
            entity_name=None,
            model="SimpleHome Scenario",
        )

    async def async_activate(self, **kwargs: Any) -> None:
        """Activate the scenario."""
        await self._hub.async_activate_scenario(self._id)
