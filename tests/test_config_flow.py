from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import AbortFlow

from custom_components.comelit.config_flow import (
    CannotConnect,
    ComelitConfigFlow,
    ComelitOptionsFlow,
    InvalidAuth,
    validate_vedo_connection,
)


def _mock_vedo_session(probe_payload: str) -> MagicMock:
    login_response = AsyncMock()
    login_response.status = 200
    login_response.headers = {"set-cookie": "uid=abc"}
    login_response.__aenter__.return_value = login_response
    probe_response = AsyncMock()
    probe_response.status = 200
    probe_response.text = AsyncMock(return_value=probe_payload)
    probe_response.__aenter__.return_value = probe_response
    session = MagicMock()
    session.post.return_value = login_response
    session.get.return_value = probe_response
    return session


@pytest.mark.asyncio
async def test_validate_vedo_connection_uses_ha_client_session() -> None:
    hass = MagicMock()
    session = _mock_vedo_session('{"logged": 1, "description": []}')

    with patch(
        "custom_components.comelit.config_flow.async_get_clientsession",
        return_value=session,
    ) as get_session, patch(
        "custom_components.comelit.config_flow.asyncio.sleep", new=AsyncMock()
    ) as sleep:
        result = await validate_vedo_connection(
            hass,
            {"host": "127.0.0.1", "port": 80, "password": "123456"},
        )

    get_session.assert_called_once_with(hass)
    # A fresh session needs a settle delay before probing it.
    sleep.assert_awaited_once()
    assert result == {"title": "Comelit Vedo (127.0.0.1)"}


@pytest.mark.asyncio
async def test_validate_vedo_connection_rejects_unauthorized_cookie() -> None:
    # The panel sets a cookie even for a wrong code; validation must probe an
    # authorized endpoint instead of trusting the cookie's presence.
    hass = MagicMock()
    session = _mock_vedo_session('{"logged": 0, "description": ["Not logged"]}')

    with patch(
        "custom_components.comelit.config_flow.async_get_clientsession",
        return_value=session,
    ), patch(
        "custom_components.comelit.config_flow.asyncio.sleep", new=AsyncMock()
    ):
        with pytest.raises(InvalidAuth):
            await validate_vedo_connection(
                hass,
                {"host": "127.0.0.1", "port": 80, "password": "999999"},
            )


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


@pytest.mark.asyncio
async def test_hub_user_flow_aborts_duplicate_unique_id() -> None:
    flow = ComelitConfigFlow()
    flow.hass = MagicMock()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock(side_effect=AbortFlow("already_configured"))

    user_input = {
        "host": "127.0.0.1",
        "port": 1883,
        "mqtt_user": "hsrv-user",
        "mqtt_password": "pwd",
        "serial": "00000000",
        "username": "user",
        "password": "hub-password",
        "client": "homeassistant",
        "scan_interval": 30,
    }

    with patch(
        "custom_components.comelit.config_flow.validate_hub_connection",
        new=AsyncMock(return_value={"title": "Comelit Hub (127.0.0.1)"}),
    ):
        with pytest.raises(AbortFlow):
            await flow.async_step_hub(user_input)

    flow.async_set_unique_id.assert_awaited_once_with("comelit_hub_00000000")
    flow._abort_if_unique_id_configured.assert_called_once()


@pytest.mark.asyncio
async def test_vedo_user_flow_shows_invalid_auth() -> None:
    flow = ComelitConfigFlow()
    flow.hass = MagicMock()
    flow._async_abort_entries_match = MagicMock()

    with patch(
        "custom_components.comelit.config_flow.validate_vedo_connection",
        new=AsyncMock(side_effect=InvalidAuth),
    ):
        result = await flow.async_step_vedo({"host": "127.0.0.1", "port": 80, "password": "bad"})

    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_auth"}


@pytest.mark.asyncio
async def test_hub_user_flow_shows_cannot_connect() -> None:
    flow = ComelitConfigFlow()
    flow.hass = MagicMock()

    with patch(
        "custom_components.comelit.config_flow.validate_hub_connection",
        new=AsyncMock(side_effect=CannotConnect),
    ):
        result = await flow.async_step_hub(
            {
                "host": "127.0.0.1",
                "port": 1883,
                "mqtt_user": "hsrv-user",
                "mqtt_password": "pwd",
                "serial": "00000000",
                "username": "user",
                "password": "hub-password",
                "client": "homeassistant",
                "scan_interval": 30,
            }
        )

    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}


def _schema_defaults(result) -> dict[str, object]:
    return {str(key): key.default() for key in result["data_schema"].schema}


@pytest.mark.asyncio
async def test_hub_user_flow_preserves_input_after_error() -> None:
    flow = ComelitConfigFlow()
    flow.hass = MagicMock()
    user_input = {
        "host": "192.168.1.10",
        "port": 1883,
        "mqtt_user": "hsrv-user",
        "mqtt_password": "mqtt-pwd",
        "serial": "ABC123",
        "username": "user",
        "password": "hub-password",
        "client": "homeassistant",
        "scan_interval": 30,
    }

    with patch(
        "custom_components.comelit.config_flow.validate_hub_connection",
        new=AsyncMock(side_effect=CannotConnect),
    ):
        result = await flow.async_step_hub(dict(user_input))

    defaults = _schema_defaults(result)
    assert defaults["host"] == "192.168.1.10"
    assert defaults["mqtt_password"] == "mqtt-pwd"
    assert defaults["serial"] == "ABC123"
    assert defaults["password"] == "hub-password"


@pytest.mark.asyncio
async def test_vedo_user_flow_preserves_input_after_error() -> None:
    flow = ComelitConfigFlow()
    flow.hass = MagicMock()
    flow._async_abort_entries_match = MagicMock()

    with patch(
        "custom_components.comelit.config_flow.validate_vedo_connection",
        new=AsyncMock(side_effect=CannotConnect),
    ):
        result = await flow.async_step_vedo(
            {"host": "192.168.1.20", "port": 8080, "password": "123456"}
        )

    defaults = _schema_defaults(result)
    assert defaults["host"] == "192.168.1.20"
    assert defaults["port"] == 8080
    assert defaults["password"] == "123456"


@pytest.mark.asyncio
async def test_options_flow_offers_only_scan_interval() -> None:
    entry = SimpleNamespace(options={}, data={"device_type": "vedo", "scan_interval": 30})
    flow = ComelitOptionsFlow(entry)

    result = await flow.async_step_init(None)

    assert {str(key) for key in result["data_schema"].schema} == {"scan_interval"}
    assert _schema_defaults(result)["scan_interval"] == 30
