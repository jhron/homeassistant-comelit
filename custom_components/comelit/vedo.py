"""Comelit Vedo async implementation."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .exception import ComelitAuthError, ComelitCommandError, ComelitConnectionError
from .vedo_coordinator import ALARM_AREA, ALARM_ZONE

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10
ARM_DISARM_ATTEMPTS = 5


class VedoRequest:
    """Vedo request endpoints."""

    ZONE_STAT = "user/zone_stat.json"
    AREA_STAT = "user/area_stat.json"
    ZONE_DESC = "user/zone_desc.json"
    AREA_DESC = "user/area_desc.json"
    LOGIN = "login.cgi"
    ACTION = "action.cgi"


class ComelitVedo:
    """Comelit Vedo coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        password: str,
        scan_interval: int,
    ) -> None:
        """Initialize the Vedo coordinator."""
        self.hass = hass
        self.host = host
        self.port = port
        self.password = password
        self.scan_interval = scan_interval
        self.entry_id: str | None = None

        self._session: aiohttp.ClientSession | None = None
        self._uid: str | None = None

        _LOGGER.debug("Initializing Comelit Vedo: %s:%s", host, port)

    async def async_connect(self) -> None:
        """Connect to Vedo."""
        self._session = async_create_clientsession(
            self.hass,
            timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT)
        )

        _LOGGER.info("Connected to Comelit Vedo")

    async def async_disconnect(self) -> None:
        """Disconnect from Vedo."""
        await self._async_logout()

        if self._session:
            await self._session.close()
            self._session = None

        _LOGGER.info("Disconnected from Comelit Vedo")

    def _build_url(self, path: str) -> str:
        """Build request URL."""
        millis = int(time.time() * 1000)
        separator = "&" if "?" in path else "?"
        return f"http://{self.host}:{self.port}/{path}{separator}_={millis}"

    def _build_headers(self, uid: str | None = None) -> dict[str, str]:
        """Build request headers."""
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:78.0) Gecko/20100101 Firefox/78.0",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "*/*",
            "Connection": "keep-alive",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept-Language": "it-IT,it;q=0.8,en-US;q=0.5,en;q=0.3",
        }
        if uid:
            headers["Cookie"] = uid
        return headers

    async def _async_login(self) -> str:
        """Login to Vedo and return session cookie."""
        if not self._session:
            raise ComelitConnectionError("Vedo session is not initialized")

        url = self._build_url(VedoRequest.LOGIN)
        headers = self._build_headers()

        try:
            async with self._session.post(
                url, data={"code": self.password}, headers=headers
            ) as response:
                if response.status != 200:
                    raise ComelitConnectionError(
                        f"Unexpected Vedo login status: {response.status}"
                    )

                uid = response.headers.get("set-cookie")
                if uid:
                    _LOGGER.debug("Logged in to Vedo")
                    return uid

                raise ComelitAuthError("Invalid Vedo credentials")
        except aiohttp.ClientError as err:
            raise ComelitConnectionError("Unable to reach Vedo panel") from err

    async def _async_logout(self) -> None:
        """Logout from Vedo."""
        if not self._session or not self._uid:
            return

        url = self._build_url(VedoRequest.LOGIN)
        headers = self._build_headers(self._uid)

        try:
            await self._session.post(url, data={"logout": 1}, headers=headers)
        except Exception:
            pass

        self._uid = None

    @property
    def authenticated(self) -> bool:
        """Return True if a Vedo session cookie is stored."""
        return self._uid is not None

    async def login(self) -> None:
        """Log in and store the current Vedo session cookie."""
        self._uid = await self._async_login()

    async def _async_get(self, path: str, parse_json: bool = True) -> Any:
        """GET request to Vedo."""
        if not self._session or not self._uid:
            return None

        url = self._build_url(path)
        headers = self._build_headers(self._uid)

        try:
            async with self._session.get(url, headers=headers) as response:
                response.raise_for_status()
                text = await response.text(encoding="iso-8859-1")
                if parse_json:
                    return json.loads(text)
                return text
        except aiohttp.ClientError as err:
            _LOGGER.error("GET request failed: %s", err)
            raise

    async def get_all_areas_and_zones(self) -> dict[str, dict[int, dict[str, Any]]]:
        """Fetch all Vedo areas and zones as a single snapshot."""
        zone_desc, zone_status, areas_desc, areas_stat = await asyncio.gather(
            self._async_get(VedoRequest.ZONE_DESC),
            self._async_get(VedoRequest.ZONE_STAT),
            self._async_get(VedoRequest.AREA_DESC),
            self._async_get(VedoRequest.AREA_STAT),
        )

        if not all([zone_desc, zone_status, areas_desc, areas_stat]):
            raise ComelitConnectionError("Failed to get Vedo data")

        zones: dict[int, dict[str, Any]] = {}
        description = zone_desc.get("description", [])
        zone_statuses = zone_status.get("status", "").split(",")
        in_area = zone_desc.get("in_area", [])

        if len(in_area) == len(zone_statuses):
            for i, value in enumerate(in_area):
                if value == "Not logged":
                    raise ComelitAuthError("Vedo cookie expired")
                if value != 0:
                    zones[i] = {
                        "id": i,
                        "name": description[i] if i < len(description) else f"Zone {i}",
                        "status": zone_statuses[i] if i < len(zone_statuses) else "0",
                    }

        areas: dict[int, dict[str, Any]] = {}
        descs = areas_desc.get("description", [])
        armed = areas_stat.get("armed", [])
        p1_pres = areas_desc.get("p1_pres", [])
        p2_pres = areas_desc.get("p2_pres", [])
        ready = areas_stat.get("ready", [])
        alarm = areas_stat.get("alarm", [])
        alarm_memory = areas_stat.get("alarm_memory", [])
        sabotage = areas_stat.get("sabotage", [])
        anomaly = areas_stat.get("anomaly", [])
        in_time = areas_stat.get("in_time", [])
        out_time = areas_stat.get("out_time", [])

        for i, name in enumerate(descs):
            areas[i] = {
                "id": i,
                "name": name,
                "armed": armed[i] if i < len(armed) else 0,
                "p1_pres": p1_pres[i] if i < len(p1_pres) else 0,
                "p2_pres": p2_pres[i] if i < len(p2_pres) else 0,
                "ready": ready[i] if i < len(ready) else 0,
                "alarm": alarm[i] if i < len(alarm) else 0,
                "alarm_memory": alarm_memory[i] if i < len(alarm_memory) else 0,
                "sabotage": sabotage[i] if i < len(sabotage) else 0,
                "anomaly": anomaly[i] if i < len(anomaly) else 0,
                "in_time": in_time[i] if i < len(in_time) else 0,
                "out_time": out_time[i] if i < len(out_time) else 0,
            }

        return {ALARM_ZONE: zones, ALARM_AREA: areas}

    async def async_arm(self, area_id: int) -> None:
        """Arm the alarm."""
        await self._async_arm_disarm("tot", area_id)

    async def async_arm_night(self, area_id: int) -> None:
        """Arm the alarm in night mode."""
        await self._async_arm_disarm("p1", area_id)

    async def async_disarm(self, area_id: int) -> None:
        """Disarm the alarm."""
        await self._async_arm_disarm("dis", area_id)

    async def _async_arm_disarm(self, action: str, area_id: int) -> None:
        """Perform arm/disarm action."""
        for attempt in range(1, ARM_DISARM_ATTEMPTS + 1):
            try:
                self._uid = await self._async_login()
                path = f"{VedoRequest.ACTION}?vedo=1&{action}={area_id}&force=1"
                await self._async_get(path, parse_json=False)
                _LOGGER.info("Arm/Disarm successful: %s area %s", action, area_id)
                await self._async_logout()
                return
            except Exception as err:
                if attempt == ARM_DISARM_ATTEMPTS:
                    _LOGGER.error("Arm/Disarm failed after %s attempts: %s", ARM_DISARM_ATTEMPTS, err)
                    raise ComelitCommandError(
                        f"Vedo arm/disarm command failed after {ARM_DISARM_ATTEMPTS} attempts"
                    ) from err
                else:
                    _LOGGER.warning("Arm/Disarm attempt %s failed, retrying...", attempt)

            await asyncio.sleep(DEFAULT_TIMEOUT)


class CookieExpired(Exception):
    """Exception for expired cookie."""

