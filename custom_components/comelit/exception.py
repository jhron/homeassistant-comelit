"""Exceptions for the Comelit integration."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError


class ComelitError(Exception):
    """Base Comelit exception."""


class ComelitCommandError(HomeAssistantError, ComelitError):
    """Raised when a Comelit command cannot be sent."""


class ComelitConnectionError(ComelitError):
    """Raised when the device cannot be reached."""


class ComelitAuthError(ComelitError):
    """Raised when authentication fails."""


class CookieException(ComelitError):
    """Backward-compatible cookie exception."""
