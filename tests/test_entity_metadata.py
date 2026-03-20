from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.components.alarm_control_panel import AlarmControlPanelState

from custom_components.comelit.alarm_control_panel import VedoAlarm
from custom_components.comelit.climate import ComelitClimate
from custom_components.comelit.sensor import HumiditySensor, TemperatureSensor


def test_climate_zone_entities_share_device_info() -> None:
    climate = ComelitClimate(
        "DOM#CL#1",
        "Living",
        {
            "auto_man": 2,
            "powerst": 0,
            "is_winter_season": True,
            "measured_temperature": 21.0,
            "target_temperature": 22.0,
        },
        MagicMock(),
    )
    temperature = TemperatureSensor("DOM#CL#1", "Living", 21.0)
    humidity = HumiditySensor("DOM#CL#1", "Living", 50)

    assert climate.device_info["identifiers"] == temperature.device_info["identifiers"]
    assert climate.device_info["identifiers"] == humidity.device_info["identifiers"]
    assert climate.device_info["name"] == "Living"


def test_vedo_alarm_exposes_alarm_state() -> None:
    alarm = VedoAlarm(1, "Area 1", AlarmControlPanelState.ARMED_AWAY, MagicMock())

    assert alarm.alarm_state is AlarmControlPanelState.ARMED_AWAY
