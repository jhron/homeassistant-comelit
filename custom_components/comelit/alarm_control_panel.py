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

from .comelit_device import ComelitDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Comelit Vedo alarm panels."""
    vedo = entry.runtime_data
    vedo.alarm_add_entities = async_add_entities
    _LOGGER.debug("Comelit Vedo Alarm Integration started")


class VedoAlarm(ComelitDevice, AlarmControlPanelEntity):
    """Representation of a Vedo alarm panel."""

    def __init__(self, id: int, description: str, state, vedo) -> None:
        """Initialize the alarm panel."""
        ComelitDevice.__init__(
            self,
            str(id),
            "vedo",
            description,
            device_id=f"vedo_area_{id}",
            entity_name=None,
            model="Vedo Area",
        )
        self._vedo = vedo
        self._state = state

    @property
    def alarm_state(self):
        """Return the current alarm state."""
        return self._state

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
