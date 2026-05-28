from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.components.alarm_control_panel import AlarmControlPanelState
from homeassistant.components.sensor import SensorStateClass

from custom_components.comelit.alarm_control_panel import VedoAlarm
from custom_components.comelit.binary_sensor import VedoSensor
from custom_components.comelit.climate import ComelitClimate
from custom_components.comelit.sensor import HumiditySensor, PowerSensor, TemperatureSensor


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


def test_numeric_sensors_expose_measurement_state_class() -> None:
    sensors = (
        PowerSensor("DOM#CN#1", "Production", 123.4, True),
        TemperatureSensor("DOM#CL#1", "Living", 21.0),
        HumiditySensor("DOM#CL#1", "Living", 50),
    )

    for sensor in sensors:
        assert sensor.state_class is SensorStateClass.MEASUREMENT


def test_vedo_binary_sensor_omits_motion_class_when_zone_type_unknown() -> None:
    sensor = VedoSensor(1, "Zone 1", "off")

    assert sensor.device_class is None


def test_vedo_entities_use_stable_parent_identifier() -> None:
    sensor = VedoSensor(1, "Zone 1", "off", parent_id="entry-id")
    alarm = VedoAlarm(
        1,
        "Area 1",
        AlarmControlPanelState.DISARMED,
        MagicMock(),
        parent_id="entry-id",
    )

    assert ("comelit", "entry-id-zone-1") in sensor.device_info["identifiers"]
    assert ("comelit", "entry-id-area-1") in alarm.device_info["identifiers"]
