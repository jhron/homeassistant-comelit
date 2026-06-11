from __future__ import annotations

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
async def test_vedo_coordinator_raises_auth_failed_when_relogin_fails() -> None:
    coordinator = _make_coordinator()
    coordinator.api.authenticated = False
    coordinator.api.login = AsyncMock(side_effect=ComelitAuthError("bad credentials"))

    with pytest.raises(ConfigEntryAuthFailed):
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


def test_vedo_authenticated_reflects_session_cookie() -> None:
    vedo = _make_vedo()

    assert vedo.authenticated is False

    vedo._uid = "uid=abc"

    assert vedo.authenticated is True
