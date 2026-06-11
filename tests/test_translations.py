from __future__ import annotations

import json
from pathlib import Path

import pytest

TRANSLATIONS = Path("custom_components/comelit/translations")

REQUIRED_STEP_FIELDS = {
    "user": {"device_type"},
    "hub": {
        "host",
        "port",
        "mqtt_user",
        "mqtt_password",
        "serial",
        "username",
        "password",
        "client",
        "scan_interval",
    },
    "vedo": {"host", "port", "password", "scan_interval"},
    "reconfigure": {
        "host",
        "port",
        "mqtt_user",
        "mqtt_password",
        "serial",
        "username",
        "password",
        "client",
    },
    "reauth_confirm": {"mqtt_user", "mqtt_password", "username", "password"},
}


@pytest.mark.parametrize("language", ["en", "cs"])
def test_translations_cover_config_flow_and_exceptions(language: str) -> None:
    data = json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))

    steps = data["config"]["step"]
    for step, fields in REQUIRED_STEP_FIELDS.items():
        assert fields <= set(steps[step]["data"]), f"{language}: step '{step}'"

    assert {"cannot_connect", "invalid_auth", "unknown"} <= set(data["config"]["error"])
    assert {"already_configured", "reconfigure_successful", "wrong_device"} <= set(
        data["config"]["abort"]
    )
    assert {"scan_interval", "enable_climate_debug"} <= set(
        data["options"]["step"]["init"]["data"]
    )
    assert {"cannot_authenticate", "update_failed"} <= set(data["exceptions"])
    assert "{error}" in data["exceptions"]["update_failed"]["message"]
