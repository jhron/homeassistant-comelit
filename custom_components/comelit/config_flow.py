"""Config flow for Comelit integration."""
from __future__ import annotations

import logging
from typing import Any, Mapping

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    CONF_DEVICE_TYPE,
    CONF_ENABLE_CLIMATE_DEBUG,
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


def _hub_schema(defaults: dict[str, Any], *, include_scan_interval: bool = True) -> vol.Schema:
    """Build the Hub config schema."""
    schema: dict[Any, Any] = {
        vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
        vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_MQTT_PORT)): int,
        vol.Required(
            CONF_MQTT_USER, default=defaults.get(CONF_MQTT_USER, DEFAULT_MQTT_USER)
        ): str,
        vol.Required(CONF_MQTT_PASSWORD, default=defaults.get(CONF_MQTT_PASSWORD, "")): str,
        vol.Required(CONF_SERIAL, default=defaults.get(CONF_SERIAL, "")): str,
        vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
        vol.Required(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
        vol.Optional(CONF_CLIENT, default=defaults.get(CONF_CLIENT, DEFAULT_CLIENT)): str,
    }
    if include_scan_interval:
        schema[
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            )
        ] = int
    return vol.Schema(schema)


def _vedo_schema(defaults: dict[str, Any], *, include_scan_interval: bool = True) -> vol.Schema:
    """Build the Vedo config schema."""
    schema: dict[Any, Any] = {
        vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
        vol.Optional(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_VEDO_PORT)): int,
        vol.Required(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
    }
    if include_scan_interval:
        schema[
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            )
        ] = int
    return vol.Schema(schema)


async def validate_hub_connection(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate Hub connection."""
    from .exception import ComelitAuthError, ComelitConnectionError
    from .hub import ComelitHub

    hub = ComelitHub(
        hass=hass,
        client_name=data.get(CONF_CLIENT, DEFAULT_CLIENT),
        hub_serial=data[CONF_SERIAL],
        hub_host=data[CONF_HOST],
        mqtt_port=data[CONF_PORT],
        mqtt_user=data[CONF_MQTT_USER],
        mqtt_password=data[CONF_MQTT_PASSWORD],
        hub_user=data[CONF_USERNAME],
        hub_password=data[CONF_PASSWORD],
        scan_interval=data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )
    try:
        await hub.async_connect()
    except ComelitAuthError as err:
        _LOGGER.error("Hub authentication failed: %s", err)
        raise InvalidAuth from err
    except ComelitConnectionError as err:
        _LOGGER.error("Failed to connect to Hub: %s", err)
        raise CannotConnect from err
    finally:
        await hub.async_disconnect()

    return {"title": f"Comelit Hub ({data[CONF_HOST]})"}


async def validate_vedo_connection(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate Vedo connection."""
    import aiohttp

    url = f"http://{data[CONF_HOST]}:{data[CONF_PORT]}/login.cgi"

    try:
        session = async_get_clientsession(hass)
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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ComelitOptionsFlow:
        """Create the options flow."""
        return ComelitOptionsFlow(config_entry)

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start a reauthentication flow for an existing entry."""
        self._device_type = entry_data[CONF_DEVICE_TYPE]
        return await self.async_step_reauth_confirm()

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
            data_schema=_hub_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_vedo(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Vedo configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._async_abort_entries_match({CONF_HOST: user_input[CONF_HOST]})
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
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="vedo",
            data_schema=_vedo_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing entry."""
        config_entry = self._get_reconfigure_entry()
        self._device_type = config_entry.data[CONF_DEVICE_TYPE]

        if self._device_type == DEVICE_TYPE_HUB:
            return await self.async_step_reconfigure_hub(user_input)
        return await self.async_step_reconfigure_vedo(user_input)

    async def async_step_reconfigure_hub(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure a Comelit Hub entry."""
        errors: dict[str, str] = {}
        config_entry = self._get_reconfigure_entry()
        current_data = dict(config_entry.data)

        if user_input is not None:
            try:
                await validate_hub_connection(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(f"comelit_hub_{user_input[CONF_SERIAL]}")
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    config_entry,
                    data_updates={
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_PORT: user_input[CONF_PORT],
                        CONF_MQTT_USER: user_input[CONF_MQTT_USER],
                        CONF_MQTT_PASSWORD: user_input[CONF_MQTT_PASSWORD],
                        CONF_SERIAL: user_input[CONF_SERIAL],
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_CLIENT: user_input.get(CONF_CLIENT, DEFAULT_CLIENT),
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_hub_schema(current_data, include_scan_interval=False),
            errors=errors,
        )

    async def async_step_reconfigure_vedo(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure a Comelit Vedo entry."""
        errors: dict[str, str] = {}
        config_entry = self._get_reconfigure_entry()
        current_data = dict(config_entry.data)

        if user_input is not None:
            self._async_abort_entries_match({CONF_HOST: user_input[CONF_HOST]})
            try:
                await validate_vedo_connection(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    config_entry,
                    data_updates={
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_PORT: user_input[CONF_PORT],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_vedo_schema(current_data, include_scan_interval=False),
            errors=errors,
        )

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm reauthentication and update credentials."""
        config_entry = self._get_reauth_entry()
        self._device_type = config_entry.data[CONF_DEVICE_TYPE]

        if self._device_type == DEVICE_TYPE_HUB:
            return await self.async_step_reauth_confirm_hub(user_input)
        return await self.async_step_reauth_confirm_vedo(user_input)

    async def async_step_reauth_confirm_hub(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reauthenticate a Comelit Hub entry."""
        errors: dict[str, str] = {}
        config_entry = self._get_reauth_entry()
        current_data = dict(config_entry.data)

        if user_input is not None:
            updated_data = {
                **current_data,
                CONF_MQTT_USER: user_input[CONF_MQTT_USER],
                CONF_MQTT_PASSWORD: user_input[CONF_MQTT_PASSWORD],
                CONF_USERNAME: user_input[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            try:
                await validate_hub_connection(self.hass, updated_data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(f"comelit_hub_{current_data[CONF_SERIAL]}")
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    config_entry,
                    data_updates={
                        CONF_MQTT_USER: user_input[CONF_MQTT_USER],
                        CONF_MQTT_PASSWORD: user_input[CONF_MQTT_PASSWORD],
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MQTT_USER,
                        default=current_data.get(CONF_MQTT_USER, DEFAULT_MQTT_USER),
                    ): str,
                    vol.Required(
                        CONF_MQTT_PASSWORD,
                        default=current_data.get(CONF_MQTT_PASSWORD, ""),
                    ): str,
                    vol.Required(
                        CONF_USERNAME,
                        default=current_data.get(CONF_USERNAME, ""),
                    ): str,
                    vol.Required(
                        CONF_PASSWORD,
                        default=current_data.get(CONF_PASSWORD, ""),
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth_confirm_vedo(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reauthenticate a Comelit Vedo entry."""
        errors: dict[str, str] = {}
        config_entry = self._get_reauth_entry()
        current_data = dict(config_entry.data)

        if user_input is not None:
            updated_data = {
                **current_data,
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            try:
                await validate_vedo_connection(self.hass, updated_data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    config_entry,
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PASSWORD,
                        default=current_data.get(CONF_PASSWORD, ""),
                    ): str,
                }
            ),
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class ComelitOptionsFlow(OptionsFlow):
    """Handle Comelit options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize Comelit options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage Comelit options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_scan_interval = self._config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self._config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        climate_debug_enabled = self._config_entry.options.get(
            CONF_ENABLE_CLIMATE_DEBUG,
            False,
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current_scan_interval): int,
                    vol.Optional(
                        CONF_ENABLE_CLIMATE_DEBUG,
                        default=climate_debug_enabled,
                    ): bool,
                }
            ),
        )
