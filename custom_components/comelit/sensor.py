"""Platform for sensor integration."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower, UnitOfTemperature
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
    """Set up Comelit sensors."""
    hub = hass.data[DOMAIN][entry.entry_id]
    hub.sensor_add_entities = async_add_entities
    _LOGGER.debug("Comelit Sensor Integration started")


class ComelitSensor(ComelitDevice, SensorEntity):
    """Representation of a Comelit sensor."""

    def __init__(
        self,
        id: str,
        description: str,
        state,
        sensor_type: str,
        icon: str,
        unit_of_measurement: str,
        device_class: SensorDeviceClass | None,
        state_class: SensorStateClass | None = None,
        *,
        device_id: str | None = None,
        model: str | None = None,
    ) -> None:
        """Initialize the sensor."""
        ComelitDevice.__init__(
            self,
            id,
            sensor_type,
            description,
            device_id=device_id,
            entity_name=None,
            model=model,
        )
        self._type = sensor_type
        self._icon = icon
        self._state = state
        self._unit_of_measurement = unit_of_measurement
        self._device_class = device_class
        self._attr_state_class = state_class

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def icon(self) -> str | None:
        """Return the icon of the sensor."""
        return self._icon

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Return the device class of the sensor."""
        return self._device_class


class PowerSensor(ComelitSensor):
    """Representation of a power sensor."""

    def __init__(self, id: str, description: str, value, prod: bool) -> None:
        """Initialize the power sensor."""
        self.prod = prod
        if prod:
            power_type = "power_prod"
            icon = "mdi:solar-power"
        else:
            power_type = "power_cons"
            icon = "mdi:power-plug"

        ComelitSensor.__init__(
            self,
            id,
            description,
            value,
            power_type,
            icon,
            UnitOfPower.WATT,
            SensorDeviceClass.POWER,
            SensorStateClass.MEASUREMENT,
            model="SimpleHome Power Meter",
        )


class TemperatureSensor(ComelitSensor):
    """Representation of a temperature sensor."""

    def __init__(self, id: str, description: str, value) -> None:
        """Initialize the temperature sensor."""
        ComelitSensor.__init__(
            self,
            id,
            description,
            value,
            "temperature",
            "mdi:home-thermometer",
            UnitOfTemperature.CELSIUS,
            SensorDeviceClass.TEMPERATURE,
            SensorStateClass.MEASUREMENT,
            device_id=id,
            model="SimpleHome Climate Zone",
        )


class HumiditySensor(ComelitSensor):
    """Representation of a humidity sensor."""

    def __init__(self, id: str, description: str, value) -> None:
        """Initialize the humidity sensor."""
        ComelitSensor.__init__(
            self,
            id,
            description,
            value,
            "humidity",
            "mdi:water-percent",
            "%",
            SensorDeviceClass.HUMIDITY,
            SensorStateClass.MEASUREMENT,
            device_id=id,
            model="SimpleHome Climate Zone",
        )
