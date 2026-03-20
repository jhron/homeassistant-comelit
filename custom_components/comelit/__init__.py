"""Comelit SimpleHome/Vedo integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
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
    CONF_ENABLE_CLIMATE_DEBUG,
    DEVICE_TYPE_HUB,
    DEVICE_TYPE_VEDO,
    PLATFORMS_HUB,
    PLATFORMS_VEDO,
)
from .exception import ComelitAuthError, ComelitConnectionError
from .hub import ComelitHub
from .vedo import ComelitVedo

_LOGGER = logging.getLogger(__name__)

type ComelitConfigEntry = ConfigEntry[ComelitHub | ComelitVedo]


def _get_scan_interval(entry: ConfigEntry) -> int:
    """Return the effective scan interval for a config entry."""
    return entry.options.get(CONF_SCAN_INTERVAL, entry.data[CONF_SCAN_INTERVAL])


def _get_enable_climate_debug(entry: ConfigEntry) -> bool:
    """Return whether detailed climate debug logging is enabled."""
    return entry.options.get(CONF_ENABLE_CLIMATE_DEBUG, False)


async def async_reload_entry(hass: HomeAssistant, entry: ComelitConfigEntry) -> None:
    """Reload a config entry after options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ComelitConfigEntry) -> bool:
    """Set up Comelit from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

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
            scan_interval=_get_scan_interval(entry),
            enable_climate_debug=_get_enable_climate_debug(entry),
        )

        try:
            await hub.async_connect()
        except ComelitAuthError as err:
            raise ConfigEntryAuthFailed(
                f"Comelit Hub authentication failed for {entry.data[CONF_HOST]}"
            ) from err
        except ComelitConnectionError as err:
            raise ConfigEntryNotReady(
                f"Unable to connect to Comelit Hub at {entry.data[CONF_HOST]}"
            ) from err

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
            scan_interval=_get_scan_interval(entry),
        )

        try:
            await vedo.async_connect()
        except ComelitAuthError as err:
            raise ConfigEntryAuthFailed(
                f"Comelit Vedo authentication failed for {entry.data[CONF_HOST]}"
            ) from err
        except ComelitConnectionError as err:
            raise ConfigEntryNotReady(
                f"Unable to connect to Comelit Vedo at {entry.data[CONF_HOST]}"
            ) from err

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

