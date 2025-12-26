"""Config flow for Comelit integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN,
    CONF_DEVICE_TYPE,
    CONF_MQTT_USER,
    CONF_MQTT_PASSWORD,
    CONF_SERIAL,
    CONF_CLIENT,
    DEVICE_TYPE_HUB,
    DEVICE_TYPE_VEDO,
    DEFAULT_MQTT_PORT,
    DEFAULT_MQTT_USER,
    DEFAULT_CLIENT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_VEDO_PORT,
)

_LOGGER = logging.getLogger(__name__)


async def validate_hub_connection(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate Hub connection."""
    import aiomqtt

    try:
        async with aiomqtt.Client(
            hostname=data[CONF_HOST],
            port=data[CONF_PORT],
            username=data[CONF_MQTT_USER],
            password=data[CONF_MQTT_PASSWORD],
        ) as client:
            # Connection successful
            pass
    except aiomqtt.MqttError as err:
        _LOGGER.error("Failed to connect to MQTT broker: %s", err)
        raise CannotConnect from err

    return {"title": f"Comelit Hub ({data[CONF_HOST]})"}


async def validate_vedo_connection(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate Vedo connection."""
    import aiohttp

    url = f"http://{data[CONF_HOST]}:{data[CONF_PORT]}/login.cgi"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                data={"code": data[CONF_PASSWORD]},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    raise CannotConnect("Invalid response from Vedo")
                if "set-cookie" not in response.headers:
                    raise InvalidAuth("Invalid password")
    except aiohttp.ClientError as err:
        _LOGGER.error("Failed to connect to Vedo: %s", err)
        raise CannotConnect from err

    return {"title": f"Comelit Vedo ({data[CONF_HOST]})"}


class ComelitConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Comelit."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._device_type: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - choose device type."""
        if user_input is not None:
            self._device_type = user_input[CONF_DEVICE_TYPE]
            if self._device_type == DEVICE_TYPE_HUB:
                return await self.async_step_hub()
            return await self.async_step_vedo()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_TYPE): vol.In(
                        {
                            DEVICE_TYPE_HUB: "Comelit SimpleHome Hub",
                            DEVICE_TYPE_VEDO: "Comelit Vedo Alarm",
                        }
                    ),
                }
            ),
        )

    async def async_step_hub(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Hub configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_hub_connection(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                user_input[CONF_DEVICE_TYPE] = DEVICE_TYPE_HUB
                await self.async_set_unique_id(f"comelit_hub_{user_input[CONF_SERIAL]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="hub",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_PORT, default=DEFAULT_MQTT_PORT): int,
                    vol.Required(CONF_MQTT_USER, default=DEFAULT_MQTT_USER): str,
                    vol.Required(CONF_MQTT_PASSWORD): str,
                    vol.Required(CONF_SERIAL): str,
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(CONF_CLIENT, default=DEFAULT_CLIENT): str,
                    vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
                }
            ),
            errors=errors,
        )

    async def async_step_vedo(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Vedo configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_vedo_connection(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                user_input[CONF_DEVICE_TYPE] = DEVICE_TYPE_VEDO
                await self.async_set_unique_id(f"comelit_vedo_{user_input[CONF_HOST]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="vedo",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_PORT, default=DEFAULT_VEDO_PORT): int,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
                }
            ),
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
