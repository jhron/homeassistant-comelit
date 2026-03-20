"""Base class for Comelit devices."""
from __future__ import annotations

from homeassistant.helpers.entity import Entity
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


class ComelitDevice(Entity):
    """Base class for Comelit devices."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        id: str,
        device_type: str | None,
        name: str,
        *,
        device_id: str | None = None,
        entity_name: str | None = None,
        manufacturer: str = "Comelit",
        model: str | None = None,
        serial_number: str | None = None,
    ) -> None:
        """Initialize the Comelit device."""
        self._is_available = True
        self._device_type = device_type
        self._id = id
        self._state = None
        self._attr_name = entity_name

        device_identifier = device_id or id
        if device_type is None:
            self._attr_unique_id = f"{DOMAIN}_{id}"
        else:
            self._attr_unique_id = f"{DOMAIN}_{device_type}_{id}"

        device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, device_identifier)},
            "manufacturer": manufacturer,
            "name": name,
        }
        if model:
            device_info["model"] = model
        if serial_number:
            device_info["serial_number"] = serial_number
        self._attr_device_info = device_info

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._is_available

    def update_state(self, state) -> None:
        """Update the device state."""
        old = self._state
        self._state = state
        if old != state:
            self.async_write_ha_state()

    def set_available(self, available: bool) -> None:
        """Update entity availability."""
        if self._is_available == available:
            return

        self._is_available = available
        self.async_write_ha_state()
