from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import STATE_CLOSED, STATE_OFF, STATE_ON

from custom_components.comelit.hub import ComelitHub
from custom_components.comelit.cover import ComelitCover
from custom_components.comelit.light import ComelitLight


def test_light_update_state_refreshes_brightness() -> None:
    light = ComelitLight("light-id", "Kitchen", STATE_ON, 255, MagicMock())
    light.async_write_ha_state = MagicMock()

    light.update_state(STATE_ON, 128)

    assert light.is_on is True
    assert light.brightness == 128


def test_light_update_state_preserves_previous_brightness_when_missing() -> None:
    light = ComelitLight("light-id", "Kitchen", STATE_ON, 200, MagicMock())
    light.async_write_ha_state = MagicMock()

    light.update_state(STATE_OFF)

    assert light.is_on is False
    assert light.brightness == 200


@pytest.mark.asyncio
async def test_cover_async_open_close_and_position() -> None:
    hub = MagicMock()
    hub.async_cover_up = AsyncMock()
    hub.async_cover_down = AsyncMock()
    hub.async_cover_position = AsyncMock()

    cover = ComelitCover("cover-id", "Shutter", STATE_CLOSED, 25, hub)
    cover.async_write_ha_state = MagicMock()

    await cover.async_open_cover()
    hub.async_cover_up.assert_awaited_once_with("cover-id")
    assert cover.is_opening is True

    await cover.async_close_cover()
    hub.async_cover_down.assert_awaited_once_with("cover-id")
    assert cover.is_closing is True

    await cover.async_set_cover_position(position=40)
    hub.async_cover_position.assert_awaited_once_with("cover-id", 60)


@pytest.mark.asyncio
async def test_cover_async_stop_uses_reverse_command() -> None:
    hub = MagicMock()
    hub.async_cover_up = AsyncMock()
    hub.async_cover_down = AsyncMock()

    cover = ComelitCover("cover-id", "Shutter", STATE_CLOSED, 25, hub)
    cover.async_write_ha_state = MagicMock()

    cover._state = "opening"
    await cover.async_stop_cover()
    hub.async_cover_down.assert_awaited_once_with("cover-id")

    hub.async_cover_up.reset_mock()
    hub.async_cover_down.reset_mock()
    cover._state = "closing"
    await cover.async_stop_cover()
    hub.async_cover_up.assert_awaited_once_with("cover-id")


@pytest.mark.asyncio
async def test_hub_light_update_passes_brightness_to_existing_entity() -> None:
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
    existing_light = MagicMock()
    hub.lights["DOM#LT#1"] = existing_light

    await hub._async_update_light(
        "DOM#LT#1",
        {"descrizione": "Kitchen", "status": "1", "type": 3, "sub_type": 4, "bright": "99"},
    )

    existing_light.update_state.assert_called_once_with(STATE_ON, 99)
