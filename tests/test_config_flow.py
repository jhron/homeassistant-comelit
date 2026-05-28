from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import AbortFlow

from custom_components.comelit.config_flow import ComelitConfigFlow, validate_vedo_connection


@pytest.mark.asyncio
async def test_validate_vedo_connection_uses_ha_client_session() -> None:
    hass = MagicMock()
    response = AsyncMock()
    response.status = 200
    response.headers = {"set-cookie": "UID=abc"}
    response.__aenter__.return_value = response
    session = MagicMock()
    session.post.return_value = response

    with patch(
        "custom_components.comelit.config_flow.async_get_clientsession",
        return_value=session,
    ) as get_session:
        result = await validate_vedo_connection(
            hass,
            {"host": "127.0.0.1", "port": 80, "password": "123456"},
        )

    get_session.assert_called_once_with(hass)
    assert result == {"title": "Comelit Vedo (127.0.0.1)"}


@pytest.mark.asyncio
async def test_vedo_user_flow_aborts_duplicate_host() -> None:
    flow = ComelitConfigFlow()
    flow.hass = MagicMock()
    flow._async_abort_entries_match = MagicMock(side_effect=AbortFlow("already_configured"))

    with pytest.raises(AbortFlow):
        await flow.async_step_vedo({"host": "127.0.0.1", "port": 80, "password": "123456"})

    flow._async_abort_entries_match.assert_called_once_with({CONF_HOST: "127.0.0.1"})


@pytest.mark.asyncio
async def test_vedo_reconfigure_aborts_on_identity_mismatch() -> None:
    flow = ComelitConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": "reconfigure"}
    entry = SimpleNamespace(
        data={
            "device_type": "vedo",
            "host": "127.0.0.1",
            "port": 80,
            "password": "123456",
        }
    )
    flow._get_reconfigure_entry = MagicMock(return_value=entry)
    flow._async_abort_entries_match = MagicMock(side_effect=AbortFlow("already_configured"))

    with pytest.raises(AbortFlow):
        await flow.async_step_reconfigure({"host": "192.168.1.50", "port": 80, "password": "123456"})

    flow._async_abort_entries_match.assert_called_once_with({CONF_HOST: "192.168.1.50"})
