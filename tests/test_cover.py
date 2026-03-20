from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.cover import CoverEntityFeature
from homeassistant.const import STATE_CLOSED, STATE_OPEN

from custom_components.comelit.cover import ComelitCover


def _make_cover(position: int = 25) -> tuple[ComelitCover, MagicMock]:
    hub = MagicMock()
    hub.async_cover_position = AsyncMock()
    cover = ComelitCover("cover-id", "Shutter", STATE_CLOSED, position, hub)
    cover.async_write_ha_state = MagicMock()
    return cover, hub


def test_cover_position_is_inverted_for_home_assistant() -> None:
    cover, _ = _make_cover(25)

    assert cover.current_cover_position == 75


def test_cover_supported_features_depend_on_position_support() -> None:
    cover_with_position, _ = _make_cover(25)
    cover_without_position, _ = _make_cover(-1)

    assert (
        cover_with_position.supported_features & CoverEntityFeature.SET_POSITION
    ) == CoverEntityFeature.SET_POSITION
    assert (
        cover_without_position.supported_features & CoverEntityFeature.SET_POSITION
    ) == 0


@pytest.mark.asyncio
async def test_async_set_cover_position_inverts_percentage_for_hub() -> None:
    cover, hub = _make_cover(25)

    await cover.async_set_cover_position(position=40)

    hub.async_cover_position.assert_awaited_once_with("cover-id", 60)


def test_cover_update_state_updates_position_and_state() -> None:
    cover, _ = _make_cover(25)

    cover.update_state(STATE_OPEN, 90)

    assert cover.is_closed is False
    assert cover.current_cover_position == 10
