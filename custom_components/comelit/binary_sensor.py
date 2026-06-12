"""Platform for binary sensor integration."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
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
    known_zones: set[int] = set()

    def _async_add_new_zones() -> None:
        zones = (coordinator.data or {}).get(ALARM_ZONE, {})
        new_sensors = [
            VedoSensor(
                zone["id"],
                zone["name"],
                parent_id=entry.entry_id,
                coordinator=coordinator,
            )
            for zone_id, zone in zones.items()
            if zone_id not in known_zones
        ]
        if new_sensors:
            known_zones.update(zones)
            async_add_entities(new_sensors)

    _async_add_new_zones()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_zones))
    _LOGGER.debug("Comelit Vedo Binary Sensor Integration started")


class VedoSensor(CoordinatorEntity, ComelitDevice, BinarySensorEntity):
    """Representation of a Vedo motion sensor."""

    def __init__(
        self,
        id: int,
        description: str,
        *,
        parent_id: str | None = None,
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

    def _zone(self):
        """Return the coordinator snapshot for this zone, if present."""
        return (self.coordinator.data or {}).get(ALARM_ZONE, {}).get(self._numeric_id)

    @property
    def available(self) -> bool:
        """Return True if the zone is present in the coordinator data."""
        return super().available and self._zone() is not None

    @property
    def is_on(self) -> bool | None:
        """Return true if motion is detected."""
        zone = self._zone()
        if zone is None:
            return None
        return (int(zone["status"], 16) & 1) != 0
