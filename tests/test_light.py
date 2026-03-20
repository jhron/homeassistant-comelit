from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode
from homeassistant.const import STATE_OFF, STATE_ON

from custom_components.comelit.light import ComelitLight


def _make_light(brightness: int | None = 255) -> tuple[ComelitLight, MagicMock]:
    hub = MagicMock()
    hub.async_light_on = AsyncMock()
    hub.async_light_off = AsyncMock()
    light = ComelitLight("light-id", "Kitchen", STATE_ON, brightness, hub)
    light.async_write_ha_state = MagicMock()
    return light, hub


def test_light_uses_onoff_mode_when_not_dimmable() -> None:
    light, _ = _make_light(None)

    assert light.supported_color_modes == {ColorMode.ONOFF}
    assert light.color_mode is ColorMode.ONOFF


@pytest.mark.asyncio
async def test_async_turn_on_updates_state_and_calls_hub() -> None:
    light, hub = _make_light(255)

    await light.async_turn_on(**{ATTR_BRIGHTNESS: 128})

    hub.async_light_on.assert_awaited_once_with("light-id", 128)
    assert light.is_on is True
    assert light.brightness == 128


@pytest.mark.asyncio
async def test_async_turn_off_updates_state_and_calls_hub() -> None:
    light, hub = _make_light(255)

    await light.async_turn_off()

    hub.async_light_off.assert_awaited_once_with("light-id")
    assert light.is_on is False
    assert light._state == STATE_OFF
