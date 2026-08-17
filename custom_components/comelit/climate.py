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
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .comelit_device import ComelitDevice

_LOGGER = logging.getLogger(__name__)

# Comelit auto_man values
COMELIT_MODE_AUTO = 1
COMELIT_MODE_MANUAL = 2
COMELIT_MODE_OFF_5 = 5
COMELIT_MODE_OFF_6 = 6

# Preset modes for HA
PRESET_MANUAL = "manual"
PRESET_AUTO = "auto"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Comelit climate entities."""
    hub = entry.runtime_data
    hub.climate_add_entities = async_add_entities
    _LOGGER.debug("Comelit Climate Integration started")


class ComelitClimate(ComelitDevice, ClimateEntity):
    """Representation of a Comelit climate device."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 5.0
    _attr_max_temp = 30.0
    _attr_target_temperature_step = 0.5
    _attr_preset_modes = [PRESET_MANUAL, PRESET_AUTO]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
    )

    def __init__(
        self,
        id: str,
        description: str,
        state_dict: dict[str, Any],
        hub,
    ) -> None:
        """Initialize the climate device."""
        ComelitDevice.__init__(
            self,
            id,
            "climate",
            description,
            device_id=id,
            entity_name=None,
            model="SimpleHome Climate Zone",
        )
        self._hub = hub
        self._climate_data = state_dict
        self._attr_hvac_modes = self._hvac_modes_for(state_dict)

    @staticmethod
    def _hvac_modes_for(state_dict: dict[str, Any]) -> list[HVACMode]:
        """Offer COOL only when the hub reports a cooling output for the zone."""
        modes = [HVACMode.OFF, HVACMode.HEAT]
        if state_dict.get("supports_cooling", True):
            modes.append(HVACMode.COOL)
        return modes

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current HVAC mode."""
        auto_man = self._climate_data.get("auto_man", COMELIT_MODE_OFF_6)
        
        if auto_man in (COMELIT_MODE_OFF_5, COMELIT_MODE_OFF_6):
            return HVACMode.OFF
        
        # For both AUTO and MANUAL, show HEAT or COOL based on season
        if self._climate_data.get("is_winter_season"):
            return HVACMode.HEAT
        return HVACMode.COOL

    @property
    def hvac_action(self) -> HVACAction:
        """Return the current HVAC action."""
        auto_man = self._climate_data.get("auto_man", COMELIT_MODE_OFF_6)
        powerst = self._climate_data.get("powerst", 0)
        
        if auto_man in (COMELIT_MODE_OFF_5, COMELIT_MODE_OFF_6):
            return HVACAction.OFF
        
        # powerst 1 = actively heating/cooling, 0 = idle
        if powerst == 1:
            if self._climate_data.get("is_winter_season"):
                return HVACAction.HEATING
            return HVACAction.COOLING
        
        return HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        auto_man = self._climate_data.get("auto_man", COMELIT_MODE_OFF_6)
        
        if auto_man == COMELIT_MODE_AUTO:
            return PRESET_AUTO
        elif auto_man == COMELIT_MODE_MANUAL:
            return PRESET_MANUAL
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        return self._climate_data.get("target_temperature")

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._climate_data.get("measured_temperature")

    @property
    def current_humidity(self) -> float | None:
        """Return the current humidity."""
        return self._climate_data.get("measured_humidity")

    def update_state(self, state_dict: dict[str, Any]) -> None:
        """Update climate state from hub data."""
        if _LOGGER.isEnabledFor(logging.DEBUG):
            changes = [
                f"{key}={self._climate_data.get(key)}->{state_dict.get(key)}"
                for key in sorted(set(self._climate_data) | set(state_dict))
                if self._climate_data.get(key) != state_dict.get(key)
            ]
            if changes:
                _LOGGER.debug("Climate update for %s: %s", self.name, ", ".join(changes))
        self._climate_data = state_dict
        self._attr_hvac_modes = self._hvac_modes_for(state_dict)
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        _LOGGER.debug("Climate command from HA for %s: set_temperature=%s", self.name, temperature)


        auto_man = self._climate_data.get("auto_man", COMELIT_MODE_OFF_6)
        
        if auto_man == COMELIT_MODE_AUTO:
            raise ServiceValidationError(
                f"Cannot set temperature in AUTO mode for {self.name}. Switch to MANUAL first."
            )
        
        if auto_man in (COMELIT_MODE_OFF_5, COMELIT_MODE_OFF_6):
            raise ServiceValidationError(
                f"Cannot set temperature when OFF for {self.name}. Turn on first."
            )
            
        await self._hub.async_climate_set_temperature(self._id, temperature)
        self._climate_data["target_temperature"] = temperature
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode."""
        _LOGGER.debug("Climate command from HA for %s: hvac_mode=%s", self.name, hvac_mode)


        if hvac_mode == HVACMode.OFF:
            await self._hub.async_climate_set_mode(self._id, COMELIT_MODE_OFF_6)
            self._climate_data["auto_man"] = COMELIT_MODE_OFF_6
        elif hvac_mode == HVACMode.HEAT:
            # Turn on in manual mode, set winter season
            await self._hub.async_climate_set_mode(self._id, COMELIT_MODE_MANUAL)
            await self._hub.async_climate_set_season(self._id, is_winter=True)
            self._climate_data["auto_man"] = COMELIT_MODE_MANUAL
            self._climate_data["is_winter_season"] = True
        elif hvac_mode == HVACMode.COOL:
            if not self._climate_data.get("supports_cooling", True):
                raise ServiceValidationError(
                    f"{self.name} has no cooling output; cooling is not supported for this zone."
                )
            # Turn on in manual mode, set summer season
            await self._hub.async_climate_set_mode(self._id, COMELIT_MODE_MANUAL)
            await self._hub.async_climate_set_season(self._id, is_winter=False)
            self._climate_data["auto_man"] = COMELIT_MODE_MANUAL
            self._climate_data["is_winter_season"] = False
        else:
            _LOGGER.warning("Unsupported HVAC mode: %s", hvac_mode)
            return
        
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode."""
        _LOGGER.debug("Climate command from HA for %s: preset_mode=%s", self.name, preset_mode)


        if preset_mode == PRESET_AUTO:
            await self._hub.async_climate_set_mode(self._id, COMELIT_MODE_AUTO)
            self._climate_data["auto_man"] = COMELIT_MODE_AUTO
        elif preset_mode == PRESET_MANUAL:
            await self._hub.async_climate_set_mode(self._id, COMELIT_MODE_MANUAL)
            self._climate_data["auto_man"] = COMELIT_MODE_MANUAL
        else:
            _LOGGER.warning("Unsupported preset mode: %s", preset_mode)
            return
        
        self.async_write_ha_state()
