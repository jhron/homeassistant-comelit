"""Exceptions for the Comelit integration."""

from __future__ import annotations


class ComelitError(Exception):
    """Base Comelit exception."""


class ComelitConnectionError(ComelitError):
    """Raised when the device cannot be reached."""


class ComelitAuthError(ComelitError):
    """Raised when authentication fails."""


class CookieException(ComelitError):
    """Backward-compatible cookie exception."""
