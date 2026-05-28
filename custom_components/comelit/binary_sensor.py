"""Platform for binary sensor integration."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .comelit_device import ComelitDevice
from .vedo_coordinator import ALARM_ZONE

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Comelit Vedo binary sensors."""
    coordinator = entry.runtime_data
    zones = (coordinator.data or {}).get(ALARM_ZONE, {})
    async_add_entities(
        VedoSensor(
            zone["id"],
            zone["name"],
            STATE_ON if (int(zone["status"], 16) & 1) != 0 else STATE_OFF,
            parent_id=entry.entry_id,
            coordinator=coordinator,
        )
        for zone in zones.values()
    )
    _LOGGER.debug("Comelit Vedo Binary Sensor Integration started")


class VedoSensor(CoordinatorEntity, ComelitDevice, BinarySensorEntity):
    """Representation of a Vedo motion sensor."""

    def __init__(
        self,
        id: int,
        description: str,
        state: str,
        *,
        parent_id: str | None = None,
        zone_type: str | None = None,
        coordinator,
    ) -> None:
        """Initialize the sensor."""
        CoordinatorEntity.__init__(self, coordinator)
        device_id = f"{parent_id}-zone-{id}" if parent_id else f"vedo-zone-{id}"
        ComelitDevice.__init__(
            self,
            str(id),
            "vedo",
            description,
            device_id=device_id,
            entity_name=None,
            model="Vedo Zone",
        )
        self._numeric_id = id
        self._state = state
        self._zone_type = zone_type

    @property
    def is_on(self) -> bool:
        """Return true if motion is detected."""
        if hasattr(self, "coordinator") and self.coordinator.data:
            zone = self.coordinator.data.get(ALARM_ZONE, {}).get(self._numeric_id)
            if zone is not None:
                return (int(zone["status"], 16) & 1) != 0
        return self._state == STATE_ON

    @property
    def device_class(self) -> BinarySensorDeviceClass | None:
        """Return the device class."""
        if self._zone_type == "motion":
            return BinarySensorDeviceClass.MOTION
        return None
