"""Base class for Comelit devices."""
from __future__ import annotations

from homeassistant.helpers.entity import Entity

from .const import DOMAIN


class ComelitDevice(Entity):
    """Base class for Comelit devices."""

    def __init__(self, id: str, device_type: str | None, name: str) -> None:
        """Initialize the Comelit device."""
        self._is_available = True
        self._device_type = device_type
        self._id = id
        self._state = None

        # Build entity name and unique_id
        name_slug = name.lower().replace(" ", "-")
        if device_type is None:
            self._name = self.entity_name = f"{DOMAIN}_{name_slug}"
            self._unique_id = f"{DOMAIN}_{id}"
        else:
            self._name = self.entity_name = f"{DOMAIN}_{device_type}_{name_slug}"
            self._unique_id = f"{DOMAIN}_{device_type}_{id}"

        self._attr_has_entity_name = False

    @property
    def name(self) -> str:
        """Return the name of the device."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._unique_id

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

    @property
    def state(self):
        """Return the state of the device."""
        return self._state

    @property
    def should_poll(self) -> bool:
        """Return False as updates are pushed."""
        return False
