from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)

from custom_components.comelit.alarm_control_panel import VedoAlarm, async_setup_entry
from custom_components.comelit.const import DOMAIN


@pytest.mark.asyncio
async def test_async_setup_entry_registers_alarm_callback() -> None:
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry-id": MagicMock()}}
    entry = SimpleNamespace(entry_id="entry-id")
    add_entities = MagicMock()

    await async_setup_entry(hass, entry, add_entities)

    assert hass.data[DOMAIN]["entry-id"].alarm_add_entities is add_entities


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
