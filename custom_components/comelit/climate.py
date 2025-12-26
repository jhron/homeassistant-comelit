"""Platform for climate integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    STATE_OFF,
    STATE_IDLE,
    STATE_ON,
    UnitOfTemperature,
)
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
    """Set up Comelit climate entities."""
    hub = hass.data[DOMAIN][entry.entry_id]
    hub.climate_add_entities = async_add_entities
    _LOGGER.info("Comelit Climate Integration started")


class ComelitClimate(ComelitDevice, ClimateEntity):
    """Representation of a Comelit climate device."""

    def __init__(
        self,
        id: str,
        description: str,
        state_dict: dict[str, Any],
        hub,
    ) -> None:
        """Initialize the climate device."""
        ComelitDevice.__init__(self, id, "climate", description)
        self._hub = hub
        self._state = state_dict

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current HVAC mode."""
        if self._state.get("status"):
            if self._state.get("is_winter_season"):
                return HVACMode.HEAT
            return HVACMode.COOL
        return HVACMode.OFF

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available HVAC modes."""
        return [HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF]

    @property
    def hvac_action(self) -> HVACAction:
        """Return the current HVAC action."""
        if self._state.get("status"):
            if self._state.get("is_winter_season"):
                return HVACAction.HEATING
            return HVACAction.COOLING
        return HVACAction.IDLE if self._state.get("is_enabled") else HVACAction.OFF

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        return self._state.get("target_temperature")

    @property
    def temperature_unit(self) -> str:
        """Return the temperature unit."""
        return UnitOfTemperature.CELSIUS

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._state.get("measured_temperature")

    @property
    def current_humidity(self) -> float | None:
        """Return the current humidity."""
        return self._state.get("measured_humidity")

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return the supported features."""
        return ClimateEntityFeature.TARGET_TEMPERATURE

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is not None:
            await self._hub.async_climate_set_temperature(self._id, temperature)
            self._state["target_temperature"] = temperature
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode."""
        await self._hub.async_climate_set_state(self._id, hvac_mode)
        self.async_write_ha_state()

    @property
    def state(self) -> str:
        """Return the current state."""
        state_mapping = {
            HVACAction.HEATING: STATE_ON,
            HVACAction.COOLING: STATE_ON,
            HVACAction.IDLE: STATE_IDLE,
            HVACAction.OFF: STATE_OFF,
        }
        return state_mapping.get(self.hvac_action, STATE_OFF)
