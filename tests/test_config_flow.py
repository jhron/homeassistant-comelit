from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.comelit.config_flow import validate_vedo_connection


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
