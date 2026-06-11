"""Platform for alarm control panel integration."""
from __future__ import annotations

import logging

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .comelit_device import ComelitDevice
from .vedo_coordinator import ALARM_AREA

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Comelit Vedo alarm panels."""
    coordinator = entry.runtime_data
    areas = (coordinator.data or {}).get(ALARM_AREA, {})
    async_add_entities(
        VedoAlarm(
            area["id"],
            area["name"],
            coordinator.api,
            parent_id=entry.entry_id,
            coordinator=coordinator,
        )
        for area in areas.values()
    )
    _LOGGER.debug("Comelit Vedo Alarm Integration started")


def _state_from_armed_value(armed: int):
    """Convert Vedo armed value to Home Assistant alarm state."""
    from homeassistant.components.alarm_control_panel import AlarmControlPanelState

    if armed == 4:
        return AlarmControlPanelState.ARMED_AWAY
    if armed == 1:
        return AlarmControlPanelState.ARMED_NIGHT
    return AlarmControlPanelState.DISARMED


class VedoAlarm(CoordinatorEntity, ComelitDevice, AlarmControlPanelEntity):
    """Representation of a Vedo alarm panel."""

    def __init__(
        self,
        id: int,
        description: str,
        vedo,
        *,
        parent_id: str | None = None,
        coordinator,
    ) -> None:
        """Initialize the alarm panel."""
        CoordinatorEntity.__init__(self, coordinator)
        device_id = f"{parent_id}-area-{id}" if parent_id else f"vedo-area-{id}"
        ComelitDevice.__init__(
            self,
            str(id),
            "vedo",
            description,
            device_id=device_id,
            entity_name=None,
            model="Vedo Area",
        )
        self._numeric_id = id
        self._vedo = vedo

    def _area(self):
        """Return the coordinator snapshot for this area, if present."""
        return (self.coordinator.data or {}).get(ALARM_AREA, {}).get(self._numeric_id)

    @property
    def available(self) -> bool:
        """Return True if the area is present in the coordinator data."""
        return super().available and self._area() is not None

    @property
    def alarm_state(self):
        """Return the current alarm state."""
        area = self._area()
        if area is None:
            return None
        return _state_from_armed_value(area["armed"])

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Disarm the alarm."""
        await self._vedo.async_disarm(int(self._id))

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Arm home - not implemented."""
        raise NotImplementedError()

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Arm away."""
        await self._vedo.async_arm(int(self._id))

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        """Arm night mode."""
        await self._vedo.async_arm_night(int(self._id))

    @property
    def code_arm_required(self) -> bool:
        """Return if code is required for arming."""
        return False

    @property
    def supported_features(self) -> AlarmControlPanelEntityFeature:
        """Return supported features."""
        return (
            AlarmControlPanelEntityFeature.ARM_AWAY
            | AlarmControlPanelEntityFeature.ARM_NIGHT
        )
