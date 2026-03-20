from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from custom_components.comelit import (
    _get_enable_climate_debug,
    _get_scan_interval,
    async_reload_entry,
    async_setup_entry,
)
from custom_components.comelit.config_flow import ComelitConfigFlow
from custom_components.comelit.const import (
    CONF_CLIENT,
    CONF_DEVICE_TYPE,
    CONF_ENABLE_CLIMATE_DEBUG,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_USER,
    CONF_SERIAL,
    DEVICE_TYPE_HUB,
    DEVICE_TYPE_VEDO,
)
from custom_components.comelit.exception import ComelitAuthError, ComelitConnectionError
from custom_components.comelit.hub import ComelitHub


def _mock_hub_entry() -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="hub-entry",
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_HUB,
            "host": "127.0.0.1",
            "port": 1883,
            CONF_MQTT_USER: "hsrv-user",
            CONF_MQTT_PASSWORD: "pwd",
            "username": "user",
            "password": "hub-password",
            CONF_SERIAL: "00000000",
            CONF_CLIENT: "homeassistant",
            "scan_interval": 30,
        },
        options={},
        add_update_listener=MagicMock(return_value=lambda: None),
        async_on_unload=MagicMock(),
    )


def _mock_vedo_entry() -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="vedo-entry",
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_VEDO,
            "host": "127.0.0.1",
            "port": 80,
            "password": "123456",
            "scan_interval": 30,
        },
        options={},
        add_update_listener=MagicMock(return_value=lambda: None),
        async_on_unload=MagicMock(),
    )


def _mock_hass() -> MagicMock:
    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    return hass


@pytest.mark.asyncio
async def test_async_setup_entry_hub_raises_not_ready() -> None:
    hass = _mock_hass()
    entry = _mock_hub_entry()

    with patch("custom_components.comelit.ComelitHub") as mock_hub_cls:
        mock_hub = mock_hub_cls.return_value
        mock_hub.async_connect = AsyncMock(side_effect=ComelitConnectionError("offline"))

        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, entry)


@pytest.mark.asyncio
async def test_async_setup_entry_hub_raises_auth_failed() -> None:
    hass = _mock_hass()
    entry = _mock_hub_entry()

    with patch("custom_components.comelit.ComelitHub") as mock_hub_cls:
        mock_hub = mock_hub_cls.return_value
        mock_hub.async_connect = AsyncMock(side_effect=ComelitAuthError("bad credentials"))

        with pytest.raises(ConfigEntryAuthFailed):
            await async_setup_entry(hass, entry)


@pytest.mark.asyncio
async def test_async_setup_entry_vedo_raises_not_ready() -> None:
    hass = _mock_hass()
    entry = _mock_vedo_entry()

    with patch("custom_components.comelit.ComelitVedo") as mock_vedo_cls:
        mock_vedo = mock_vedo_cls.return_value
        mock_vedo.async_connect = AsyncMock(side_effect=ComelitConnectionError("offline"))

        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, entry)


@pytest.mark.asyncio
async def test_hub_reconnect_loop_restores_availability() -> None:
    hass = MagicMock()
    hass.async_create_background_task = MagicMock()

    hub = ComelitHub(
        hass=hass,
        client_name="homeassistant",
        hub_serial="00000000",
        hub_host="127.0.0.1",
        mqtt_port=1883,
        mqtt_user="hsrv-user",
        mqtt_password="pwd",
        hub_user="user",
        hub_password="hub-password",
        scan_interval=30,
    )

    sensor = MagicMock()
    hub.sensors["sensor"] = sensor
    hub._async_cleanup_connection = AsyncMock()
    hub._async_open_connection = AsyncMock(
        side_effect=[ComelitConnectionError("offline"), None]
    )

    with patch("custom_components.comelit.hub.asyncio.sleep", new=AsyncMock()):
        await hub._async_reconnect_loop("connection lost")

    assert sensor.set_available.call_args_list[0].args == (False,)
    assert sensor.set_available.call_args_list[-1].args == (True,)
    assert hub._async_open_connection.await_count == 2


@pytest.mark.asyncio
async def test_handle_status_clears_pending_flag() -> None:
    hass = MagicMock()
    hass.async_create_background_task = MagicMock()

    hub = ComelitHub(
        hass=hass,
        client_name="homeassistant",
        hub_serial="00000000",
        hub_host="127.0.0.1",
        mqtt_port=1883,
        mqtt_user="hsrv-user",
        mqtt_password="pwd",
        hub_user="user",
        hub_password="hub-password",
        scan_interval=30,
    )

    hub._status_request_pending = True

    await hub._async_handle_status({})

    assert hub._status_request_pending is False


def test_get_scan_interval_prefers_options() -> None:
    entry = _mock_hub_entry()
    entry.options = {"scan_interval": 5}

    assert _get_scan_interval(entry) == 5


def test_get_enable_climate_debug_defaults_to_false() -> None:
    entry = _mock_hub_entry()

    assert _get_enable_climate_debug(entry) is False


def test_get_enable_climate_debug_prefers_options() -> None:
    entry = _mock_hub_entry()
    entry.options = {CONF_ENABLE_CLIMATE_DEBUG: True}

    assert _get_enable_climate_debug(entry) is True


@pytest.mark.asyncio
async def test_async_setup_entry_uses_scan_interval_from_options() -> None:
    hass = _mock_hass()
    entry = _mock_hub_entry()
    entry.options = {"scan_interval": 5, CONF_ENABLE_CLIMATE_DEBUG: True}

    with patch("custom_components.comelit.ComelitHub") as mock_hub_cls:
        mock_hub = mock_hub_cls.return_value
        mock_hub.async_connect = AsyncMock()

        assert await async_setup_entry(hass, entry) is True

    assert mock_hub_cls.call_args.kwargs["scan_interval"] == 5
    assert mock_hub_cls.call_args.kwargs["enable_climate_debug"] is True
    entry.add_update_listener.assert_called_once()
    entry.async_on_unload.assert_called_once()


@pytest.mark.asyncio
async def test_async_reload_entry_reloads_config_entry() -> None:
    hass = _mock_hass()
    hass.config_entries.async_reload = AsyncMock()
    entry = _mock_hub_entry()

    await async_reload_entry(hass, entry)

    hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)


@pytest.mark.asyncio
async def test_hub_reconfigure_updates_existing_entry() -> None:
    flow = ComelitConfigFlow()
    flow.hass = _mock_hass()
    flow.context = {"source": "reconfigure"}
    entry = _mock_hub_entry()
    flow._get_reconfigure_entry = MagicMock(return_value=entry)
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_mismatch = MagicMock()
    flow.async_update_reload_and_abort = MagicMock(
        return_value={"type": "abort", "reason": "reconfigure_successful"}
    )

    user_input = dict(entry.data)
    user_input["host"] = "192.168.1.200"

    with patch(
        "custom_components.comelit.config_flow.validate_hub_connection",
        new=AsyncMock(return_value={"title": "Comelit Hub (192.168.1.200)"}),
    ):
        result = await flow.async_step_reconfigure(user_input)

    assert result["reason"] == "reconfigure_successful"
    flow.async_set_unique_id.assert_awaited_once_with("comelit_hub_00000000")
    flow._abort_if_unique_id_mismatch.assert_called_once_with(reason="wrong_device")
    flow.async_update_reload_and_abort.assert_called_once_with(
        entry,
        data_updates={
            "host": "192.168.1.200",
            "port": 1883,
            CONF_MQTT_USER: "hsrv-user",
            CONF_MQTT_PASSWORD: "pwd",
            CONF_SERIAL: "00000000",
            "username": "user",
            "password": "hub-password",
            CONF_CLIENT: "homeassistant",
        },
    )


@pytest.mark.asyncio
async def test_vedo_reconfigure_updates_existing_entry() -> None:
    flow = ComelitConfigFlow()
    flow.hass = _mock_hass()
    flow.context = {"source": "reconfigure"}
    entry = _mock_vedo_entry()
    flow._get_reconfigure_entry = MagicMock(return_value=entry)
    flow.async_update_reload_and_abort = MagicMock(
        return_value={"type": "abort", "reason": "reconfigure_successful"}
    )

    user_input = dict(entry.data)
    user_input["host"] = "192.168.1.50"

    with patch(
        "custom_components.comelit.config_flow.validate_vedo_connection",
        new=AsyncMock(return_value={"title": "Comelit Vedo (192.168.1.50)"}),
    ):
        result = await flow.async_step_reconfigure(user_input)

    assert result["reason"] == "reconfigure_successful"
    flow.async_update_reload_and_abort.assert_called_once_with(
        entry,
        data_updates={
            "host": "192.168.1.50",
            "port": 80,
            "password": "123456",
        },
    )
