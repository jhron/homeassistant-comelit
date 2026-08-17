from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiomqtt
import pytest

from custom_components.comelit.exception import ComelitCommandError, ComelitConnectionError
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


@pytest.mark.asyncio
async def test_hub_reauth_watchdog_clears_stuck_reauth() -> None:
    hub = _make_hub()
    hub._reauth_in_progress = True
    hub._reauth_started_at = time.monotonic() - 31

    hub._clear_stale_reauth()

    assert hub._reauth_in_progress is False


@pytest.mark.asyncio
async def test_hub_connect_error_includes_broker_error_detail() -> None:
    hub = _make_hub()
    client = MagicMock()
    client.__aenter__.side_effect = aiomqtt.MqttError("[Errno 111] Connection refused")

    with patch("custom_components.comelit.hub.aiomqtt.Client", return_value=client):
        with pytest.raises(ComelitConnectionError, match="Connection refused"):
            await hub.async_connect()


@pytest.mark.asyncio
async def test_hub_dispatch_clears_reauth_when_announce_publish_fails() -> None:
    hub = _make_hub()
    hub._async_announce = AsyncMock(side_effect=ComelitCommandError("publish failed"))
    payload = {"req_result": 1, "message": "invalid token", "seq_id": 7}

    await hub._async_dispatch(payload)

    assert hub._reauth_in_progress is False
    assert hub._reauth_started_at == 0.0


@pytest.mark.asyncio
async def test_hub_records_unsolicited_payload_when_debug_enabled() -> None:
    hub = _make_hub()
    hub.enable_payload_debug = True
    hub._status_request_pending = False
    payload = {"req_type": 0, "out_data": [{"elements": []}]}

    await hub._async_dispatch(payload)

    assert hub._last_unsolicited_payload == payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "act_type", "act_params"),
    [
        (1, 13, [1]),  # AUTO
        (2, 13, [2]),  # MANUAL
        (5, 0, [0]),  # OFF (auto)
        (6, 0, [0]),  # OFF (manual)
    ],
)
async def test_hub_climate_set_mode_publishes_hsrv_action(
    mode: int, act_type: int, act_params: list[int]
) -> None:
    """Mode switching uses HSrv act_type=13 with the target auto_man value.

    Verified against a real hub: act_type=13 also turns an OFF zone back on,
    while the previously used act_type=1/3 was silently ignored.
    """
    hub = _make_hub()
    hub._async_publish = AsyncMock()

    await hub.async_climate_set_mode("DOM#CL#73.1", mode)

    hub._async_publish.assert_awaited_once_with(
        {
            "req_type": 1,
            "req_sub_type": 3,
            "obj_id": "DOM#CL#73.1",
            "act_type": act_type,
            "act_params": act_params,
        }
    )


@pytest.mark.asyncio
async def test_hub_climate_set_mode_ignores_unknown_mode() -> None:
    hub = _make_hub()
    hub._async_publish = AsyncMock()

    await hub.async_climate_set_mode("DOM#CL#73.1", 9)

    hub._async_publish.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outputs", "supports_cooling"),
    [
        ({"num_moduloI": "2", "num_uscitaI": "6", "num_moduloE": "0", "num_moduloE_ana": "0", "num_moduloIE": "0", "num_moduloIE_ana": "0"}, False),
        ({"num_moduloI": "2", "num_uscitaI": "3", "num_moduloE": "2", "num_uscitaE": "3", "num_moduloIE": "0"}, True),
        ({"num_moduloE": "0", "num_moduloIE": "5"}, True),  # combined heat/cool output
        ({}, True),  # firmware without output fields: keep offering cool
    ],
)
async def test_hub_climate_state_reports_cooling_support(
    outputs: dict[str, str], supports_cooling: bool
) -> None:
    """Zones without any cooling (E / IE) output module do not support cooling."""
    hub = _make_hub()
    hub.climate_add_entities = MagicMock()
    data = {"descrizione": "Bagno", "temperatura": "239", "soglia_attiva": "220", "auto_man": "6", **outputs}

    await hub._async_update_climate("DOM#CL#75.1", data)

    assert hub.climates["DOM#CL#75.1"]._climate_data["supports_cooling"] is supports_cooling
