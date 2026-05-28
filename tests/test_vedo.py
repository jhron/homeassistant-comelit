from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.alarm_control_panel import AlarmControlPanelState

from custom_components.comelit.exception import ComelitCommandError
from custom_components.comelit.vedo import ComelitVedo


def _make_vedo() -> ComelitVedo:
    hass = MagicMock()
    hass.async_create_background_task = MagicMock()
    return ComelitVedo(
        hass=hass,
        host="127.0.0.1",
        port=80,
        password="pwd",
        scan_interval=30,
    )


@pytest.mark.asyncio
async def test_async_update_sensor_adds_and_updates_binary_sensor() -> None:
    vedo = _make_vedo()
    vedo.binary_sensor_add_entities = MagicMock()

    await vedo._async_update_sensor(
        {"id": 1, "name": "Garage", "status": "0011"}
    )

    assert len(vedo.sensors) == 1
    vedo.sensors[1].async_write_ha_state = MagicMock()
    assert vedo.sensors[1].is_on is True

    await vedo._async_update_sensor(
        {"id": 1, "name": "Garage", "status": "0000"}
    )

    assert len(vedo.sensors) == 1
    assert vedo.sensors[1].is_on is False


@pytest.mark.asyncio
async def test_async_update_area_maps_alarm_state_and_updates_existing_entity() -> None:
    vedo = _make_vedo()
    vedo.alarm_add_entities = MagicMock()

    await vedo._async_update_area({"id": 0, "name": "Main", "armed": 4})

    assert len(vedo.areas) == 1
    vedo.areas[0].async_write_ha_state = MagicMock()
    assert vedo.areas[0].alarm_state is AlarmControlPanelState.ARMED_AWAY

    await vedo._async_update_area({"id": 0, "name": "Main", "armed": 1})
    assert vedo.areas[0].alarm_state is AlarmControlPanelState.ARMED_NIGHT

    await vedo._async_update_area({"id": 0, "name": "Main", "armed": 0})
    assert vedo.areas[0].alarm_state is AlarmControlPanelState.DISARMED


@pytest.mark.asyncio
async def test_async_arm_disarm_retries_failed_login_and_reuses_new_cookie() -> None:
    vedo = _make_vedo()
    vedo._async_login = AsyncMock(side_effect=[RuntimeError("boom"), "uid=abc"])
    vedo._async_get = AsyncMock()
    vedo._async_logout = AsyncMock()

    with patch("custom_components.comelit.vedo.asyncio.sleep", new=AsyncMock()):
        await vedo._async_arm_disarm("dis", 2)

    assert vedo._async_login.await_count == 2
    vedo._async_get.assert_awaited_once_with(
        "action.cgi?vedo=1&dis=2&force=1",
        parse_json=False,
    )
    vedo._async_logout.assert_awaited_once()


@pytest.mark.asyncio
async def test_vedo_arm_disarm_raises_after_retry_exhaustion() -> None:
    vedo = _make_vedo()
    vedo._async_login = AsyncMock(side_effect=RuntimeError("offline"))

    with patch("custom_components.comelit.vedo.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(ComelitCommandError, match="failed after 5 attempts"):
            await vedo.async_arm(1)
