from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.comelit import async_setup_entry, async_unload_entry
from custom_components.comelit.const import (
    CONF_CLIENT,
    CONF_DEVICE_TYPE,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_USER,
    CONF_SERIAL,
    DEVICE_TYPE_HUB,
    DEVICE_TYPE_VEDO,
    DOMAIN,
    PLATFORMS_HUB,
    PLATFORMS_VEDO,
)


def _mock_hass() -> MagicMock:
    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass


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
        runtime_data=None,
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
        runtime_data=None,
        add_update_listener=MagicMock(return_value=lambda: None),
        async_on_unload=MagicMock(),
    )


@pytest.mark.asyncio
async def test_async_setup_entry_hub_success_sets_runtime_data() -> None:
    hass = _mock_hass()
    entry = _mock_hub_entry()

    with patch("custom_components.comelit.ComelitHub") as mock_hub_cls:
        mock_hub = mock_hub_cls.return_value
        mock_hub.async_connect = AsyncMock()

        assert await async_setup_entry(hass, entry) is True

    assert hass.data[DOMAIN][entry.entry_id] is mock_hub
    assert entry.runtime_data is mock_hub
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, PLATFORMS_HUB
    )
    entry.add_update_listener.assert_called_once()
    entry.async_on_unload.assert_called_once()


@pytest.mark.asyncio
async def test_async_setup_entry_vedo_success_sets_runtime_data() -> None:
    hass = _mock_hass()
    entry = _mock_vedo_entry()

    with (
        patch("custom_components.comelit.ComelitVedo") as mock_vedo_cls,
        patch("custom_components.comelit.ComelitVedoCoordinator") as mock_coordinator_cls,
    ):
        mock_vedo = mock_vedo_cls.return_value
        mock_vedo.async_connect = AsyncMock()
        mock_coordinator = mock_coordinator_cls.return_value
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()

        assert await async_setup_entry(hass, entry) is True

    assert hass.data[DOMAIN][entry.entry_id] is mock_coordinator
    assert entry.runtime_data is mock_coordinator
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, PLATFORMS_VEDO
    )
    entry.add_update_listener.assert_called_once()
    entry.async_on_unload.assert_called_once()


@pytest.mark.asyncio
async def test_async_setup_entry_hub_cleans_up_when_forward_setup_fails() -> None:
    hass = _mock_hass()
    entry = _mock_hub_entry()
    hass.config_entries.async_forward_entry_setups = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("custom_components.comelit.ComelitHub") as mock_hub_cls:
        mock_hub = mock_hub_cls.return_value
        mock_hub.async_connect = AsyncMock()
        mock_hub.async_disconnect = AsyncMock()

        with pytest.raises(RuntimeError, match="boom"):
            await async_setup_entry(hass, entry)

    mock_hub.async_disconnect.assert_awaited_once()
    assert entry.entry_id not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_async_setup_entry_vedo_cleans_up_when_forward_setup_fails() -> None:
    hass = _mock_hass()
    entry = _mock_vedo_entry()
    hass.config_entries.async_forward_entry_setups = AsyncMock(side_effect=RuntimeError("boom"))

    with (
        patch("custom_components.comelit.ComelitVedo") as mock_vedo_cls,
        patch("custom_components.comelit.ComelitVedoCoordinator") as mock_coordinator_cls,
    ):
        mock_vedo = mock_vedo_cls.return_value
        mock_vedo.async_connect = AsyncMock()
        mock_coordinator = mock_coordinator_cls.return_value
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        mock_coordinator.async_disconnect = AsyncMock()

        with pytest.raises(RuntimeError, match="boom"):
            await async_setup_entry(hass, entry)

    mock_coordinator.async_disconnect.assert_awaited_once()
    assert entry.entry_id not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_async_setup_entry_vedo_cleans_up_when_first_refresh_fails() -> None:
    hass = _mock_hass()
    entry = _mock_vedo_entry()

    with (
        patch("custom_components.comelit.ComelitVedo") as mock_vedo_cls,
        patch("custom_components.comelit.ComelitVedoCoordinator") as mock_coordinator_cls,
    ):
        mock_vedo = mock_vedo_cls.return_value
        mock_vedo.async_connect = AsyncMock()
        mock_coordinator = mock_coordinator_cls.return_value
        mock_coordinator.async_config_entry_first_refresh = AsyncMock(
            side_effect=RuntimeError("refresh failed")
        )
        mock_coordinator.async_disconnect = AsyncMock()

        with pytest.raises(RuntimeError, match="refresh failed"):
            await async_setup_entry(hass, entry)

    mock_coordinator.async_disconnect.assert_awaited_once()
    assert entry.entry_id not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_async_unload_entry_hub_disconnects_runtime_data() -> None:
    hass = _mock_hass()
    entry = _mock_hub_entry()
    runtime = MagicMock()
    runtime.async_disconnect = AsyncMock()
    hass.data[DOMAIN] = {entry.entry_id: runtime}

    assert await async_unload_entry(hass, entry) is True

    hass.config_entries.async_unload_platforms.assert_awaited_once_with(
        entry, PLATFORMS_HUB
    )
    runtime.async_disconnect.assert_awaited_once()
    assert entry.entry_id not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_async_unload_entry_vedo_disconnects_runtime_data() -> None:
    hass = _mock_hass()
    entry = _mock_vedo_entry()
    runtime = MagicMock()
    runtime.async_disconnect = AsyncMock()
    hass.data[DOMAIN] = {entry.entry_id: runtime}

    assert await async_unload_entry(hass, entry) is True

    hass.config_entries.async_unload_platforms.assert_awaited_once_with(
        entry, PLATFORMS_VEDO
    )
    runtime.async_disconnect.assert_awaited_once()
    assert entry.entry_id not in hass.data[DOMAIN]
