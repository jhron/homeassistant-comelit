"""Platform for binary sensor integration."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .comelit_device import ComelitDevice
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Comelit Vedo binary sensors."""
    vedo = hass.data[DOMAIN][entry.entry_id]
    vedo.binary_sensor_add_entities = async_add_entities
    _LOGGER.info("Comelit Vedo Binary Sensor Integration started")


class VedoSensor(ComelitDevice, BinarySensorEntity):
    """Representation of a Vedo motion sensor."""

    def __init__(self, id: int, description: str, state: str) -> None:
        """Initialize the sensor."""
        ComelitDevice.__init__(self, str(id), "vedo", description)
        self._state = state

    @property
    def is_on(self) -> bool:
        """Return true if motion is detected."""
        return self._state == STATE_ON

    @property
    def device_class(self) -> BinarySensorDeviceClass:
        """Return the device class."""
        return BinarySensorDeviceClass.MOTION
