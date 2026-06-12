from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.comelit.exception import (
    ComelitAuthError,
    ComelitCommandError,
    ComelitConnectionError,
)
from custom_components.comelit.vedo import ComelitVedo
from custom_components.comelit.vedo_coordinator import ComelitVedoCoordinator


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


@pytest.mark.asyncio
async def test_vedo_async_connect_uses_ha_created_client_session() -> None:
    vedo = _make_vedo()
    session = MagicMock()
    vedo._async_login = AsyncMock(return_value="uid=abc")
    vedo.hass.async_create_background_task.side_effect = (
        lambda coroutine, _name: coroutine.close()
    )

    with patch(
        "custom_components.comelit.vedo.async_create_clientsession",
        return_value=session,
    ) as create_session:
        await vedo.async_connect()

    create_session.assert_called_once()
    assert create_session.call_args.args == (vedo.hass,)
    assert create_session.call_args.kwargs["timeout"].total == 15
    assert vedo._session is session


def _make_coordinator() -> ComelitVedoCoordinator:
    return ComelitVedoCoordinator(
        hass=MagicMock(),
        api=MagicMock(),
        entry=SimpleNamespace(entry_id="entry-id", async_on_unload=MagicMock()),
        scan_interval=30,
    )


def test_vedo_coordinator_binds_config_entry() -> None:
    entry = SimpleNamespace(entry_id="entry-id", async_on_unload=MagicMock())

    coordinator = ComelitVedoCoordinator(
        hass=MagicMock(),
        api=MagicMock(),
        entry=entry,
        scan_interval=30,
    )

    assert coordinator.config_entry is entry
    entry.async_on_unload.assert_called_once()


@pytest.mark.asyncio
async def test_vedo_coordinator_refresh_returns_zone_and_area_snapshot() -> None:
    coordinator = _make_coordinator()
    coordinator.api.authenticated = False
    coordinator.api.login = AsyncMock()
    coordinator.api.get_all_areas_and_zones = AsyncMock(
        return_value={"alarm_zone": {1: MagicMock(index=1)}, "alarm_area": {1: MagicMock(index=1)}}
    )

    data = await coordinator._async_update_data()

    assert set(data) == {"alarm_zone", "alarm_area"}
    coordinator.api.login.assert_awaited_once()


@pytest.mark.asyncio
async def test_vedo_coordinator_reuses_active_session_without_login() -> None:
    coordinator = _make_coordinator()
    coordinator.api.authenticated = True
    coordinator.api.login = AsyncMock()
    coordinator.api.get_all_areas_and_zones = AsyncMock(
        return_value={"alarm_zone": {}, "alarm_area": {}}
    )

    await coordinator._async_update_data()

    coordinator.api.login.assert_not_awaited()


@pytest.mark.asyncio
async def test_vedo_coordinator_relogs_in_once_when_cookie_expired() -> None:
    snapshot = {"alarm_zone": {}, "alarm_area": {}}
    coordinator = _make_coordinator()
    coordinator.api.authenticated = True
    coordinator.api.login = AsyncMock()
    coordinator.api.get_all_areas_and_zones = AsyncMock(
        side_effect=[ComelitAuthError("Vedo cookie expired"), snapshot]
    )

    data = await coordinator._async_update_data()

    coordinator.api.login.assert_awaited_once()
    assert data == snapshot


@pytest.mark.asyncio
async def test_vedo_coordinator_escalates_to_reauth_only_after_repeated_auth_failures() -> None:
    # The panel under load can report "logged": 0 even for a valid session, so
    # a couple of failed cycles must not pop the reauth dialog.
    coordinator = _make_coordinator()
    coordinator.api.authenticated = False
    coordinator.api.login = AsyncMock(side_effect=ComelitAuthError("bad code"))

    for _ in range(2):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_vedo_coordinator_resets_auth_failure_counter_on_success() -> None:
    snapshot = {"alarm_zone": {}, "alarm_area": {}}
    coordinator = _make_coordinator()
    coordinator.api.authenticated = True
    coordinator.api.login = AsyncMock()

    coordinator.api.get_all_areas_and_zones = AsyncMock(side_effect=ComelitAuthError("x"))
    for _ in range(2):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    coordinator.api.get_all_areas_and_zones = AsyncMock(return_value=snapshot)
    assert await coordinator._async_update_data() == snapshot

    coordinator.api.get_all_areas_and_zones = AsyncMock(side_effect=ComelitAuthError("x"))
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_vedo_coordinator_raises_update_failed_on_connection_error() -> None:
    coordinator = _make_coordinator()
    coordinator.api.authenticated = True
    coordinator.api.get_all_areas_and_zones = AsyncMock(
        side_effect=ComelitConnectionError("offline")
    )

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_vedo_coordinator_retries_once_on_transient_connection_error() -> None:
    # A single slow poll on the panel must not flip entities to unavailable
    # or log an update failure - one retry absorbs the transient timeout.
    snapshot = {"alarm_zone": {}, "alarm_area": {}}
    coordinator = _make_coordinator()
    coordinator.api.authenticated = True
    coordinator.api.login = AsyncMock()
    coordinator.api.get_all_areas_and_zones = AsyncMock(
        side_effect=[ComelitConnectionError("timeout"), snapshot]
    )

    data = await coordinator._async_update_data()

    assert data == snapshot
    coordinator.api.login.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_all_areas_and_zones_fetches_endpoints_sequentially() -> None:
    # The panel's embedded web server cannot keep up with concurrent requests
    # under continuous polling, so at most one request may be in flight.
    vedo = _make_vedo()
    responses = {
        "user/zone_desc.json": {"description": ["Zone 1"], "in_area": [1]},
        "user/zone_stat.json": {"status": "0000"},
        "user/area_desc.json": {"description": ["Area 1"], "p1_pres": [0], "p2_pres": [0]},
        "user/area_stat.json": {
            "armed": [0],
            "ready": [0],
            "alarm": [0],
            "alarm_memory": [0],
            "sabotage": [0],
            "anomaly": [0],
            "in_time": [0],
            "out_time": [0],
        },
    }
    in_flight = 0
    max_in_flight = 0
    calls: list[str] = []

    async def fake_get(path: str, parse_json: bool = True):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        calls.append(path)
        await asyncio.sleep(0)
        in_flight -= 1
        return responses[path]

    vedo._async_get = fake_get

    data = await vedo.get_all_areas_and_zones()

    assert max_in_flight == 1
    assert calls == [
        "user/zone_desc.json",
        "user/zone_stat.json",
        "user/area_desc.json",
        "user/area_stat.json",
    ]
    assert data["alarm_zone"][0]["name"] == "Zone 1"
    assert data["alarm_area"][0]["name"] == "Area 1"


@pytest.mark.asyncio
async def test_login_probes_session_and_raises_on_unauthorized_cookie() -> None:
    # The panel sets a cookie even for a wrong code; only an authorized
    # request reveals whether the login actually succeeded.
    vedo = _make_vedo()
    vedo._async_logout = AsyncMock()
    vedo._async_login = AsyncMock(return_value="uid=abc")
    vedo._async_get = AsyncMock(side_effect=ComelitAuthError("not logged"))

    with pytest.raises(ComelitAuthError):
        await vedo.login()

    vedo._async_get.assert_awaited_once_with("user/area_desc.json")


@pytest.mark.asyncio
async def test_login_logs_out_stale_session_before_logging_in() -> None:
    vedo = _make_vedo()
    vedo._async_logout = AsyncMock()
    vedo._async_login = AsyncMock(return_value="uid=new")
    vedo._async_get = AsyncMock(return_value={"logged": 1})

    await vedo.login()

    vedo._async_logout.assert_awaited_once()
    assert vedo._uid == "uid=new"


def test_vedo_authenticated_reflects_session_cookie() -> None:
    vedo = _make_vedo()

    assert vedo.authenticated is False

    vedo._uid = "uid=abc"

    assert vedo.authenticated is True


class _FakeResponse:
    def __init__(self, payload) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    async def text(self, encoding=None) -> str:
        return json.dumps(self._payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


@pytest.mark.asyncio
async def test_async_get_raises_auth_error_when_panel_reports_not_logged() -> None:
    # Real Vedo panels answer expired sessions with HTTP 200 and "logged": 0.
    vedo = _make_vedo()
    vedo._uid = "uid=abc"
    vedo._session = MagicMock()
    vedo._session.get = MagicMock(
        return_value=_FakeResponse(
            {
                "logged": 0,
                "rt_stat": 80,
                "present": "Not logged",
                "in_area": ["Not logged"],
                "description": ["Not logged"],
            }
        )
    )

    with pytest.raises(ComelitAuthError):
        await vedo._async_get("user/zone_desc.json")


def _vedo_responses(zone_desc: dict, zone_stat: dict) -> dict[str, dict]:
    return {
        "user/zone_desc.json": zone_desc,
        "user/zone_stat.json": zone_stat,
        "user/area_desc.json": {"description": ["Area 1"], "p1_pres": [0], "p2_pres": [0]},
        "user/area_stat.json": {
            "armed": [0],
            "ready": [0],
            "alarm": [0],
            "alarm_memory": [0],
            "sabotage": [0],
            "anomaly": [0],
            "in_time": [0],
            "out_time": [0],
        },
    }


def _patch_responses(vedo: ComelitVedo, responses: dict[str, dict]) -> None:
    async def fake_get(path: str, parse_json: bool = True):
        return responses[path]

    vedo._async_get = fake_get


@pytest.mark.asyncio
async def test_zones_created_only_for_slots_with_description() -> None:
    # Real panels mark unconfigured padding slots with empty descriptions while
    # in_area stays non-zero, so the description is the only usable predicate.
    vedo = _make_vedo()
    _patch_responses(
        vedo,
        _vedo_responses(
            {"description": ["Zona 24H", "", "VIALE", ""], "in_area": [2, 1, 5, 1]},
            {"status": "0020,0200,0000,0200"},
        ),
    )

    data = await vedo.get_all_areas_and_zones()

    assert set(data["alarm_zone"]) == {0, 2}
    assert data["alarm_zone"][2] == {"id": 2, "name": "VIALE", "status": "0000"}


@pytest.mark.asyncio
async def test_zone_parsing_survives_status_length_mismatch() -> None:
    # Regression: a length mismatch between in_area and status used to skip the
    # whole zone loop silently, leaving the integration without any zones.
    vedo = _make_vedo()
    _patch_responses(
        vedo,
        _vedo_responses(
            {"description": ["VIALE", "PISCINA"], "in_area": [5]},
            {"status": "0200"},
        ),
    )

    data = await vedo.get_all_areas_and_zones()

    assert set(data["alarm_zone"]) == {0, 1}
    assert data["alarm_zone"][0]["status"] == "0200"
    assert data["alarm_zone"][1]["status"] == "0000"


@pytest.mark.asyncio
async def test_async_get_converts_timeout_to_connection_error() -> None:
    # aiohttp raises asyncio.TimeoutError when ClientTimeout expires; it must
    # surface as ComelitConnectionError so the coordinator can retry once.
    vedo = _make_vedo()
    vedo._uid = "uid=abc"
    vedo._session = MagicMock()

    class _TimeoutContext:
        async def __aenter__(self):
            raise asyncio.TimeoutError

        async def __aexit__(self, *exc) -> bool:
            return False

    vedo._session.get = MagicMock(return_value=_TimeoutContext())

    with pytest.raises(ComelitConnectionError):
        await vedo._async_get("user/zone_stat.json")


@pytest.mark.asyncio
async def test_get_all_areas_and_zones_propagates_auth_error_from_single_endpoint() -> None:
    # A session invalidated mid-snapshot must surface as an auth error so the
    # coordinator logs in again, instead of producing a partial snapshot.
    vedo = _make_vedo()
    responses = _vedo_responses(
        {"description": ["VIALE"], "in_area": [5]},
        {"status": "0200"},
    )

    async def fake_get(path: str, parse_json: bool = True):
        if path == "user/zone_desc.json":
            raise ComelitAuthError("Vedo session is not logged in")
        return responses[path]

    vedo._async_get = fake_get

    with pytest.raises(ComelitAuthError):
        await vedo.get_all_areas_and_zones()
