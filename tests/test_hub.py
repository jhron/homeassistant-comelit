from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiomqtt
import pytest

from custom_components.comelit.exception import ComelitCommandError
from custom_components.comelit.hub import ComelitHub


def _load_status() -> dict:
    with Path("tests/hub_status.json").open(encoding="utf-8") as json_file:
        return json.load(json_file)


def _make_hub() -> ComelitHub:
    hass = MagicMock()
    hass.async_create_background_task = MagicMock()
    return ComelitHub(
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


@pytest.mark.asyncio
async def test_handle_status_creates_entities_from_fixture_snapshot() -> None:
    hub = _make_hub()
    hub.sensor_add_entities = MagicMock()
    hub.light_add_entities = MagicMock()
    hub.cover_add_entities = MagicMock()
    hub.climate_add_entities = MagicMock()
    hub.scene_add_entities = MagicMock()
    hub.switch_add_entities = MagicMock()

    await hub._async_handle_status(_load_status())

    assert len(hub.sensors) == 6
    assert len(hub.lights) == 11
    assert len(hub.covers) == 2
    assert len(hub.climates) == 2
    assert len(hub.scenes) == 1
    assert len(hub.switches) == 2
    assert "DOM#CL#2.1" in hub.climates
    assert "GEN#SC#4" in hub.scenes
    assert "DOM#LD#5.2" in hub.switches


@pytest.mark.asyncio
async def test_handle_status_second_snapshot_does_not_duplicate_entities() -> None:
    hub = _make_hub()
    hub.sensor_add_entities = MagicMock()
    hub.light_add_entities = MagicMock()
    hub.cover_add_entities = MagicMock()
    hub.climate_add_entities = MagicMock()
    hub.scene_add_entities = MagicMock()
    hub.switch_add_entities = MagicMock()
    status = _load_status()

    await hub._async_handle_status(status)

    sensor_calls = hub.sensor_add_entities.call_count
    light_calls = hub.light_add_entities.call_count
    cover_calls = hub.cover_add_entities.call_count
    climate_calls = hub.climate_add_entities.call_count
    scene_calls = hub.scene_add_entities.call_count
    switch_calls = hub.switch_add_entities.call_count

    await hub._async_handle_status(status)

    assert len(hub.sensors) == 6
    assert len(hub.lights) == 11
    assert len(hub.covers) == 2
    assert len(hub.climates) == 2
    assert len(hub.scenes) == 1
    assert len(hub.switches) == 2
    assert hub.sensor_add_entities.call_count == sensor_calls
    assert hub.light_add_entities.call_count == light_calls
    assert hub.cover_add_entities.call_count == cover_calls
    assert hub.climate_add_entities.call_count == climate_calls
    assert hub.scene_add_entities.call_count == scene_calls
    assert hub.switch_add_entities.call_count == switch_calls


@pytest.mark.asyncio
async def test_update_entities_yields_during_large_batches() -> None:
    hub = _make_hub()
    elements = [{"id": f"UNKNOWN#{index}", "data": {"id": f"UNKNOWN#{index}"}} for index in range(11)]

    with patch("custom_components.comelit.hub.asyncio.sleep", new=AsyncMock()) as mock_sleep:
        await hub._async_update_entities(elements)

    mock_sleep.assert_awaited_once_with(0)


@pytest.mark.asyncio
async def test_hub_power_sensor_uses_float_native_value() -> None:
    hub = _make_hub()
    added: list = []
    hub.sensor_add_entities = added.extend

    await hub._async_update_sensor(
        "DOM#CN#1",
        {"descrizione": "Main", "instant_power": "2244.000000", "prod": "0"},
    )

    assert added[0].native_value == 2244.0
    assert isinstance(added[0].native_value, float)


@pytest.mark.asyncio
async def test_hub_humidity_sensor_uses_float_native_value() -> None:
    hub = _make_hub()
    added: list = []
    hub.sensor_add_entities = added.extend

    await hub._async_update_sensor(
        "DOM#CL#1",
        {
            "descrizione": "Living",
            "temperatura": "210",
            "umidita": "50",
            "type": 9,
            "sub_type": 16,
        },
    )

    humidity = next(sensor for sensor in added if sensor.unique_id.endswith("_humidity_DOM#CL#1"))
    assert humidity.native_value == 50.0
    assert isinstance(humidity.native_value, float)


@pytest.mark.asyncio
async def test_hub_publish_without_client_raises_command_error() -> None:
    hub = _make_hub()

    with pytest.raises(ComelitCommandError, match="MQTT client is not connected"):
        await hub._async_publish({"req_type": 1})


@pytest.mark.asyncio
async def test_hub_publish_mqtt_error_raises_and_clears_pending_status() -> None:
    hub = _make_hub()
    hub._client = MagicMock()
    hub._client.publish = AsyncMock(side_effect=aiomqtt.MqttError("offline"))
    hub._status_request_pending = True
    hub._schedule_reconnect = MagicMock()

    with pytest.raises(ComelitCommandError, match="Failed to publish"):
        await hub._async_publish({"req_type": 0})

    assert hub._status_request_pending is False
    hub._schedule_reconnect.assert_called_once()
