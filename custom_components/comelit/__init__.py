"""Comelit SimpleHome/Vedo integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    CONF_DEVICE_TYPE,
    CONF_MQTT_USER,
    CONF_MQTT_PASSWORD,
    CONF_SERIAL,
    CONF_CLIENT,
    DEVICE_TYPE_HUB,
    DEVICE_TYPE_VEDO,
    PLATFORMS_HUB,
    PLATFORMS_VEDO,
)
from .hub import ComelitHub
from .vedo import ComelitVedo

_LOGGER = logging.getLogger(__name__)

type ComelitConfigEntry = ConfigEntry[ComelitHub | ComelitVedo]


async def async_setup_entry(hass: HomeAssistant, entry: ComelitConfigEntry) -> bool:
    """Set up Comelit from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    device_type = entry.data[CONF_DEVICE_TYPE]

    if device_type == DEVICE_TYPE_HUB:
        hub = ComelitHub(
            hass=hass,
            client_name=entry.data[CONF_CLIENT],
            hub_serial=entry.data[CONF_SERIAL],
            hub_host=entry.data[CONF_HOST],
            mqtt_port=entry.data[CONF_PORT],
            mqtt_user=entry.data[CONF_MQTT_USER],
            mqtt_password=entry.data[CONF_MQTT_PASSWORD],
            hub_user=entry.data[CONF_USERNAME],
            hub_password=entry.data[CONF_PASSWORD],
            scan_interval=entry.data[CONF_SCAN_INTERVAL],
        )

        if not await hub.async_connect():
            return False

        hass.data[DOMAIN][entry.entry_id] = hub
        entry.runtime_data = hub

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_HUB)
        _LOGGER.info("Comelit SimpleHome Hub integration started")

    elif device_type == DEVICE_TYPE_VEDO:
        vedo = ComelitVedo(
            hass=hass,
            host=entry.data[CONF_HOST],
            port=entry.data[CONF_PORT],
            password=entry.data[CONF_PASSWORD],
            scan_interval=entry.data[CONF_SCAN_INTERVAL],
        )

        if not await vedo.async_connect():
            return False

        hass.data[DOMAIN][entry.entry_id] = vedo
        entry.runtime_data = vedo

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_VEDO)
        _LOGGER.info("Comelit Vedo integration started")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ComelitConfigEntry) -> bool:
    """Unload a config entry."""
    device_type = entry.data[CONF_DEVICE_TYPE]

    if device_type == DEVICE_TYPE_HUB:
        platforms = PLATFORMS_HUB
    else:
        platforms = PLATFORMS_VEDO

    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)

    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_disconnect()

    return unload_ok

