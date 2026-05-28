from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)

from custom_components.comelit.alarm_control_panel import (
    VedoAlarm,
    async_setup_entry as async_setup_alarm_entry,
)
from custom_components.comelit.binary_sensor import async_setup_entry as async_setup_binary_sensor_entry
from custom_components.comelit.climate import async_setup_entry as async_setup_climate_entry
from custom_components.comelit.cover import async_setup_entry as async_setup_cover_entry
from custom_components.comelit.light import async_setup_entry as async_setup_light_entry
from custom_components.comelit.scene import async_setup_entry as async_setup_scene_entry
from custom_components.comelit.sensor import async_setup_entry as async_setup_sensor_entry
from custom_components.comelit.switch import async_setup_entry as async_setup_switch_entry
from custom_components.comelit.vedo_coordinator import ALARM_AREA, ALARM_ZONE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("setup_entry", "callback_attr"),
    [
        (async_setup_climate_entry, "climate_add_entities"),
        (async_setup_cover_entry, "cover_add_entities"),
        (async_setup_light_entry, "light_add_entities"),
        (async_setup_scene_entry, "scene_add_entities"),
        (async_setup_sensor_entry, "sensor_add_entities"),
        (async_setup_switch_entry, "switch_add_entities"),
    ],
)
async def test_platform_setup_uses_entry_runtime_data(setup_entry, callback_attr: str) -> None:
    hass = MagicMock()
    runtime = MagicMock()
    entry = SimpleNamespace(entry_id="entry-id", runtime_data=runtime)
    add_entities = MagicMock()

    await setup_entry(hass, entry, add_entities)

    assert getattr(runtime, callback_attr) is add_entities


@pytest.mark.asyncio
async def test_alarm_setup_adds_entities_from_coordinator_snapshot() -> None:
    hass = MagicMock()
    runtime = MagicMock()
    runtime.api = MagicMock()
    runtime.data = {
        ALARM_AREA: {
            1: {"id": 1, "name": "Area 1", "armed": 4},
        }
    }
    entry = SimpleNamespace(entry_id="entry-id", runtime_data=runtime)
    add_entities = MagicMock()

    await async_setup_alarm_entry(hass, entry, add_entities)

    entities = list(add_entities.call_args.args[0])
    assert len(entities) == 1
    assert entities[0].alarm_state is AlarmControlPanelState.ARMED_AWAY


@pytest.mark.asyncio
async def test_binary_sensor_setup_adds_entities_from_coordinator_snapshot() -> None:
    hass = MagicMock()
    runtime = MagicMock()
    runtime.data = {
        ALARM_ZONE: {
            1: {"id": 1, "name": "Zone 1", "status": "0011"},
        }
    }
    entry = SimpleNamespace(entry_id="entry-id", runtime_data=runtime)
    add_entities = MagicMock()

    await async_setup_binary_sensor_entry(hass, entry, add_entities)

    entities = list(add_entities.call_args.args[0])
    assert len(entities) == 1
    assert entities[0].is_on is True


@pytest.mark.asyncio
async def test_vedo_alarm_async_methods_delegate_to_vedo_runtime() -> None:
    vedo = MagicMock()
    vedo.async_disarm = AsyncMock()
    vedo.async_arm = AsyncMock()
    vedo.async_arm_night = AsyncMock()
    alarm = VedoAlarm(1, "Area 1", AlarmControlPanelState.ARMED_AWAY, vedo)

    await alarm.async_alarm_disarm()
    await alarm.async_alarm_arm_away()
    await alarm.async_alarm_arm_night()

    vedo.async_disarm.assert_awaited_once_with(1)
    vedo.async_arm.assert_awaited_once_with(1)
    vedo.async_arm_night.assert_awaited_once_with(1)


def test_vedo_alarm_properties_expose_supported_state() -> None:
    alarm = VedoAlarm(1, "Area 1", AlarmControlPanelState.ARMED_AWAY, MagicMock())

    assert alarm.alarm_state is AlarmControlPanelState.ARMED_AWAY
    assert (
        alarm.supported_features
        == AlarmControlPanelEntityFeature.ARM_AWAY
        | AlarmControlPanelEntityFeature.ARM_NIGHT
    )
    assert alarm.code_arm_required is False


@pytest.mark.asyncio
async def test_vedo_alarm_arm_home_is_not_supported() -> None:
    alarm = VedoAlarm(1, "Area 1", AlarmControlPanelState.DISARMED, MagicMock())

    with pytest.raises(NotImplementedError):
        await alarm.async_alarm_arm_home()
