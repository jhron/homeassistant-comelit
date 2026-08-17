"""Comelit Hub async implementation."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import suppress
from typing import Any, Callable

import aiomqtt

from homeassistant.const import (
    STATE_CLOSED,
    STATE_OPEN,
    STATE_CLOSING,
    STATE_OPENING,
    STATE_ON,
    STATE_OFF,
    STATE_UNKNOWN,
)
from homeassistant.components.climate import HVACMode
from homeassistant.core import HomeAssistant

from .exception import ComelitAuthError, ComelitCommandError, ComelitConnectionError

_LOGGER = logging.getLogger(__name__)

HANDSHAKE_TIMEOUT = 15
RECONNECT_DELAY = 10
STATUS_STALE_TIMEOUT = 15
ENTITY_BATCH_YIELD = 10
REAUTH_TIMEOUT = 30


class RequestType:
    """Request type constants."""

    STATUS = 0
    LIGHT = 1
    AUTOMATION = 1
    TEMPERATURE = 1
    COVER = 1
    SCENARIO = 1
    ANNOUNCE = 13
    LOGIN = 5
    PARAMETERS = 8


class HubFields:
    """Hub field constants."""

    TOKEN = "sessiontoken"
    TEMPERATURE = "temperatura"
    TARGET_TEMPERATURE = "soglia_attiva"
    HUMIDITY = "umidita"
    DESCRIPTION = "descrizione"
    INSTANT_POWER = "instant_power"
    ID = "id"
    PRODUCTION = "prod"
    ELEMENTS = "elements"
    COVER_STATUS = "open_status"
    STATUS = "status"
    DATA = "data"
    PARAMETER_NAME = "param_name"
    PARAMETER_VALUE = "param_value"
    SUB_TYPE = "sub_type"
    WINTER_SEASON = "est_inv"


class HubClasses:
    """Hub class constants."""

    LOGICAL = "GEN#PL"
    AUTOMATION = "DOM#AU"
    LIGHT = "DOM#LT"
    FTV = "DOM#CN"
    POWER_CONSUMPTION = "DOM#CN"
    LOAD = "DOM#LC"
    TEMPERATURE = "DOM#CL"
    SCENARIO = "DOM#LD"
    COVER = "DOM#BL"
    SCENARIO = "GEN#SC"
    OTHER = "DOM#LD"


# Cooling output modules reported per climate zone: summer (E) and combined
# winter/summer (IE) relays plus their analog variants. Heating-only zones report
# "0" for all of them (verified on a real hub).
COOLING_OUTPUT_FIELDS = ("num_moduloE", "num_moduloE_ana", "num_moduloIE", "num_moduloIE_ana")


def _has_cooling_output(data: dict[str, Any]) -> bool:
    """Return whether the zone has any cooling output; unknown layouts keep cooling."""
    values = [str(data[field]).strip() for field in COOLING_OUTPUT_FIELDS if field in data]
    if not values:
        return True
    return any(value not in ("", "0") for value in values)


class ComelitHub:
    """Comelit Hub coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        client_name: str,
        hub_serial: str,
        hub_host: str,
        mqtt_port: int,
        mqtt_user: str,
        mqtt_password: str,
        hub_user: str,
        hub_password: str,
        scan_interval: int,
    ) -> None:
        """Initialize the hub."""
        self.hass = hass
        self.client_name = client_name
        self.hub_serial = hub_serial
        self.hub_host = hub_host
        self.mqtt_port = mqtt_port
        self.mqtt_user = mqtt_user
        self.mqtt_password = mqtt_password
        self.hub_user = hub_user
        self.hub_password = hub_password
        self.scan_interval = scan_interval

        self.sequence_id = 1
        self.agent_id = 10
        self.sessiontoken = ""
        self._reauth_in_progress = False  # Prevent re-auth loops
        self._last_reauth_time = 0  # Timestamp of last re-auth attempt
        self._reauth_started_at = 0.0

        self.topic_rx = f"HSrv/{hub_serial}/rx/{client_name}"
        self.topic_tx = f"HSrv/{hub_serial}/tx/{client_name}"

        self._client: aiomqtt.Client | None = None
        self._connected = False
        self._shutdown = False
        self._listen_task: asyncio.Task | None = None
        self._process_task: asyncio.Task | None = None
        self._status_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._announce_event = asyncio.Event()
        self._login_event = asyncio.Event()
        self._login_error: str | None = None
        self._status_request_pending = False
        self._last_status_request = 0.0
        self.enable_payload_debug = False
        self._last_unsolicited_payload: dict[str, Any] | None = None

        # Entity storage
        self.sensors: dict[str, Any] = {}
        self.climates: dict[str, Any] = {}
        self.lights: dict[str, Any] = {}
        self.covers: dict[str, Any] = {}
        self.scenes: dict[str, Any] = {}
        self.switches: dict[str, Any] = {}

        # Entity add callbacks
        self.sensor_add_entities: Callable | None = None
        self.climate_add_entities: Callable | None = None
        self.light_add_entities: Callable | None = None
        self.cover_add_entities: Callable | None = None
        self.scene_add_entities: Callable | None = None
        self.switch_add_entities: Callable | None = None

        _LOGGER.debug(
            "Initializing Comelit Hub: %s:%s serial=%s",
            hub_host,
            mqtt_port,
            hub_serial,
        )

    async def async_connect(self) -> None:
        """Connect to the MQTT broker."""
        self._shutdown = False
        await self._async_open_connection()

    async def _async_open_connection(self) -> None:
        """Open the MQTT connection and complete the hub login handshake."""
        try:
            self._announce_event.clear()
            self._login_event.clear()
            self._login_error = None
            self.sessiontoken = ""
            self._reauth_in_progress = False
            self._reauth_started_at = 0.0

            self._client = aiomqtt.Client(
                hostname=self.hub_host,
                port=self.mqtt_port,
                username=self.mqtt_user,
                password=self.mqtt_password,
            )
            await self._client.__aenter__()
            await self._client.subscribe(self.topic_tx)
            self._connected = True

            # Start listener task (just receives messages, puts them in queue)
            self._listen_task = self.hass.async_create_background_task(
                self._async_listen(), "comelit_hub_listen"
            )

            # Start message processor task (processes messages from queue)
            self._process_task = self.hass.async_create_background_task(
                self._async_process_messages(), "comelit_hub_process"
            )

            # Send announce
            await self._async_announce()

            await asyncio.wait_for(self._announce_event.wait(), timeout=HANDSHAKE_TIMEOUT)
            await asyncio.wait_for(self._login_event.wait(), timeout=HANDSHAKE_TIMEOUT)

            if self._login_error:
                raise ComelitAuthError(self._login_error)

            if not self.sessiontoken:
                raise ComelitAuthError("Comelit Hub login did not return a session token")

            # Start status update task
            self._status_task = self.hass.async_create_background_task(
                self._async_status_updater(), "comelit_hub_status"
            )

            self._set_entities_available(True)
            _LOGGER.info("Connected to Comelit Hub")

        except ComelitAuthError:
            await self._async_cleanup_connection()
            raise
        except asyncio.TimeoutError as err:
            await self._async_cleanup_connection()
            raise ComelitConnectionError("Timed out during Comelit Hub handshake") from err
        except aiomqtt.MqttError as err:
            await self._async_cleanup_connection()
            raise ComelitConnectionError(
                f"Failed to connect to Comelit MQTT broker: {err}"
            ) from err

    async def async_disconnect(self) -> None:
        """Disconnect from the MQTT broker."""
        self._shutdown = True

        if self._reconnect_task:
            self._reconnect_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._reconnect_task
            self._reconnect_task = None

        await self._async_cleanup_connection()
        _LOGGER.info("Disconnected from Comelit Hub")

    async def _async_cleanup_connection(self) -> None:
        """Clean up the active MQTT connection and worker tasks."""
        self._connected = False
        self._announce_event.clear()
        self._login_event.clear()
        self._login_error = None
        self.sessiontoken = ""
        self._reauth_in_progress = False
        self._reauth_started_at = 0.0
        self._status_request_pending = False
        self._last_status_request = 0.0

        current_task = asyncio.current_task()

        if self._listen_task:
            self._listen_task.cancel()
            if self._listen_task is not current_task:
                with suppress(asyncio.CancelledError):
                    await self._listen_task
            self._listen_task = None

        if self._process_task:
            self._process_task.cancel()
            if self._process_task is not current_task:
                with suppress(asyncio.CancelledError):
                    await self._process_task
            self._process_task = None

        if self._status_task:
            self._status_task.cancel()
            if self._status_task is not current_task:
                with suppress(asyncio.CancelledError):
                    await self._status_task
            self._status_task = None

        if self._client:
            with suppress(aiomqtt.MqttError):
                await self._client.__aexit__(None, None, None)
            self._client = None

        while True:
            try:
                self._message_queue.get_nowait()
                self._message_queue.task_done()
            except asyncio.QueueEmpty:
                break

    def _set_entities_available(self, available: bool) -> None:
        """Update availability for all known entities."""
        entity_maps = (
            self.sensors,
            self.climates,
            self.lights,
            self.covers,
            self.scenes,
            self.switches,
        )
        for entity_map in entity_maps:
            for entity in entity_map.values():
                if hasattr(entity, "set_available"):
                    entity.set_available(available)

    def _schedule_reconnect(self, reason: str) -> None:
        """Schedule a reconnect attempt after connection loss."""
        if self._shutdown:
            return

        if self._reconnect_task and not self._reconnect_task.done():
            return

        _LOGGER.warning("Comelit Hub connection lost: %s", reason)
        self._reconnect_task = self.hass.async_create_background_task(
            self._async_reconnect_loop(reason),
            "comelit_hub_reconnect",
        )

    async def _async_reconnect_loop(self, reason: str) -> None:
        """Reconnect to the hub until successful or shutting down."""
        try:
            await self._async_cleanup_connection()
            self._set_entities_available(False)

            while not self._shutdown:
                try:
                    _LOGGER.info("Attempting Comelit Hub reconnect after: %s", reason)
                    await self._async_open_connection()
                    self._set_entities_available(True)
                    _LOGGER.info("Comelit Hub reconnect successful")
                    return
                except ComelitAuthError as err:
                    _LOGGER.error("Comelit Hub reconnect aborted due to authentication failure: %s", err)
                    return
                except ComelitConnectionError as err:
                    _LOGGER.warning(
                        "Comelit Hub reconnect failed, retrying in %s seconds: %s",
                        RECONNECT_DELAY,
                        err,
                    )
                    await asyncio.sleep(RECONNECT_DELAY)

            _LOGGER.debug("Comelit Hub reconnect loop stopped")
        finally:
            self._reconnect_task = None

    async def _async_listen(self) -> None:
        """Listen for MQTT messages and put them in queue."""
        try:
            async for message in self._client.messages:
                try:
                    payload = json.loads(message.payload)
                    self._message_queue.put_nowait(payload)
                except json.JSONDecodeError as err:
                    _LOGGER.error("Failed to decode message: %s", err)
        except aiomqtt.MqttError as err:
            if self._connected:
                self._schedule_reconnect(str(err))

    async def _async_process_messages(self) -> None:
        """Process messages from the queue."""
        while self._connected:
            try:
                # Wait for message with timeout to allow checking _connected flag
                try:
                    payload = await asyncio.wait_for(
                        self._message_queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                await self._async_dispatch(payload)
                self._message_queue.task_done()

            except Exception as err:
                _LOGGER.exception("Error processing message: %s", err)

    async def _async_status_updater(self) -> None:
        """Periodically request status updates."""
        while self._connected:
            self._clear_stale_reauth()

            # Only request status if we have a valid token and not re-authenticating
            status_is_stale = (
                self._status_request_pending
                and (time.monotonic() - self._last_status_request) > max(self.scan_interval * 2, STATUS_STALE_TIMEOUT)
            )
            if status_is_stale:
                _LOGGER.debug("Clearing stale pending status request")
                self._status_request_pending = False

            if (
                self.sessiontoken
                and not self._reauth_in_progress
                and not self._status_request_pending
            ):
                await self._async_update_status()
            await asyncio.sleep(self.scan_interval)

    def _clear_stale_reauth(self) -> None:
        """Clear a reauth attempt that did not receive a login response."""
        if not self._reauth_in_progress:
            return
        if (time.monotonic() - self._reauth_started_at) <= REAUTH_TIMEOUT:
            return

        _LOGGER.warning("Comelit Hub reauthentication timed out")
        self._reauth_in_progress = False
        self._reauth_started_at = 0.0
        self._status_request_pending = False

    async def _async_publish(self, data: dict[str, Any]) -> None:
        """Publish a message to the hub."""
        if not self._client:
            self._status_request_pending = False
            raise ComelitCommandError("Comelit MQTT client is not connected")

        data["seq_id"] = self.sequence_id
        data["agent_id"] = self.agent_id
        data["sessiontoken"] = self.sessiontoken

        try:
            await self._client.publish(self.topic_rx, json.dumps(data))
            self.sequence_id += 1
        except aiomqtt.MqttError as err:
            self._status_request_pending = False
            self._schedule_reconnect(f"publish failed: {err}")
            raise ComelitCommandError(f"Failed to publish Comelit command: {err}") from err

    async def _async_dispatch(self, payload: dict[str, Any]) -> None:
        """Dispatch incoming messages."""
        # Check for invalid token on any response
        if payload.get("req_result") == 1 and "invalid token" in payload.get("message", "").lower():
            current_time = time.time()
            # Only re-auth if not already in progress and at least 5 seconds since last attempt
            if not self._reauth_in_progress and (current_time - self._last_reauth_time) > 5:
                _LOGGER.warning("Token expired (seq_id=%s), re-authenticating...", payload.get("seq_id"))
                self._reauth_in_progress = True
                self._last_reauth_time = current_time
                self._reauth_started_at = time.monotonic()
                self.sessiontoken = ""
                try:
                    await self._async_announce()
                except ComelitCommandError as err:
                    _LOGGER.warning("Re-authentication announce failed: %s", err)
                    self._reauth_in_progress = False
                    self._reauth_started_at = 0.0
            else:
                _LOGGER.debug("Ignoring invalid token response (seq_id=%s) - re-auth in progress or cooldown", 
                             payload.get("seq_id"))
            return

        if self.enable_payload_debug and not self._status_request_pending:
            self._last_unsolicited_payload = payload
            _LOGGER.debug("Comelit Hub unsolicited payload observed: %s", payload)
        
        req_type = payload.get("req_type")

        if req_type == RequestType.ANNOUNCE:
            await self._async_handle_announce(payload)
        elif req_type == RequestType.LOGIN:
            if payload.get("req_result") == 1:
                self._login_error = payload.get("message", "Authentication failed")
                self._login_event.set()
                return

            self._handle_token(payload)
            self._reauth_in_progress = False  # Re-auth complete
            self._reauth_started_at = 0.0
        elif req_type == RequestType.STATUS:
            await self._async_handle_status(payload)
        elif req_type == RequestType.PARAMETERS:
            self._handle_parameters(payload)

    async def _async_announce(self) -> None:
        """Send announce request."""
        await self._async_publish({
            "req_type": RequestType.ANNOUNCE,
            "req_sub_type": -1,
            "agent_type": 0,
        })

    async def _async_handle_announce(self, payload: dict[str, Any]) -> None:
        """Handle announce response."""
        self.agent_id = payload["out_data"][0]["agent_id"]
        self._announce_event.set()
        _LOGGER.debug("Announce received. Agent ID: %s", self.agent_id)

        await self._async_publish({
            "req_type": RequestType.LOGIN,
            "req_sub_type": -1,
            "agent_type": 0,
            "user_name": self.hub_user,
            "password": self.hub_password,
        })

    def _handle_token(self, payload: dict[str, Any]) -> None:
        """Handle login response."""
        self.sessiontoken = payload.get(HubFields.TOKEN, "")
        if not self.sessiontoken:
            self._login_error = payload.get("message", "Authentication failed")
        self._login_event.set()
        _LOGGER.debug("Received session token")

    def _handle_parameters(self, payload: dict[str, Any]) -> None:
        """Handle parameters response."""
        # Parameters handling - kept for compatibility
        pass

    async def _async_update_status(self) -> None:
        """Request status update."""
        self._status_request_pending = True
        self._last_status_request = time.monotonic()
        await self._async_publish({
            "req_type": RequestType.STATUS,
            "req_sub_type": -1,
            "obj_id": "GEN#17#13#1",
            "detail_level": 1,
        })

    async def _async_handle_status(self, payload: dict[str, Any]) -> None:
        """Handle status response."""
        try:
            if "out_data" not in payload:
                _LOGGER.debug("Status response without out_data: %s", payload)
                return
                
            out_data = payload["out_data"]
            if not out_data or not isinstance(out_data, list):
                return
                
            first_item = out_data[0]
            if HubFields.ELEMENTS not in first_item:
                _LOGGER.debug("Status response without elements: %s", payload)
                return
                
            elements = first_item[HubFields.ELEMENTS]
            await self._async_update_entities(elements)
        except Exception as err:
            _LOGGER.error("Error handling status: %s", err)
        finally:
            self._status_request_pending = False

    async def _async_update_entities(self, elements: list[dict[str, Any]]) -> None:
        """Update entities from status response."""
        for index, item in enumerate(elements, start=1):
            try:
                entity_id = item.get(HubFields.ID, "")

                # Handle logical elements recursively
                if HubClasses.LOGICAL in entity_id:
                    logical_elements = item.get(HubFields.DATA, {}).get(HubFields.ELEMENTS, [])
                    for logical_element in logical_elements:
                        logical_data = logical_element.get(HubFields.DATA, {})
                        if HubClasses.LOGICAL in logical_data.get(HubFields.ID, ""):
                            await self._async_update_entities(logical_data.get(HubFields.ELEMENTS, []))
                        else:
                            await self._async_update_entities([logical_data])

                # Get item data
                item_data = item.get(HubFields.DATA, item)

                if HubClasses.POWER_CONSUMPTION in entity_id or HubClasses.FTV in entity_id:
                    await self._async_update_sensor(entity_id, item_data)
                elif HubClasses.TEMPERATURE in entity_id:
                    await self._async_update_sensor(entity_id, item_data)
                    if item_data.get(HubFields.SUB_TYPE) in (16, 12):
                        await self._async_update_climate(entity_id, item_data)
                elif HubClasses.LIGHT in entity_id:
                    await self._async_update_light(entity_id, item_data)
                elif HubClasses.COVER in entity_id:
                    await self._async_update_cover(entity_id, item_data, HubFields.COVER_STATUS)
                elif HubClasses.AUTOMATION in entity_id:
                    await self._async_update_cover(entity_id, item_data, HubFields.STATUS)
                elif HubClasses.SCENARIO in entity_id:
                    await self._async_update_scenario(entity_id, item_data)
                elif HubClasses.OTHER in entity_id:
                    await self._async_update_switch(entity_id, item_data)

            except Exception as err:
                _LOGGER.error("Error updating entity %s: %s", item, err)

            if index % ENTITY_BATCH_YIELD == 0:
                await asyncio.sleep(0)

    async def _async_update_sensor(self, entity_id: str, data: dict[str, Any]) -> None:
        """Update or create sensor entity."""
        from .sensor import PowerSensor, TemperatureSensor, HumiditySensor

        description = data.get(HubFields.DESCRIPTION, "")

        try:
            if HubClasses.POWER_CONSUMPTION in entity_id or HubClasses.FTV in entity_id:
                value = round(float(data[HubFields.INSTANT_POWER]), 2)
                prod = data.get(HubFields.PRODUCTION) == "1"
                sensor = PowerSensor(entity_id, description, value, prod)
            else:
                value = float(format(float(data[HubFields.TEMPERATURE]), ".1f")) / 10
                sensor = TemperatureSensor(entity_id, description, value)

                # Add humidity sensor if available
                if data.get("type") == 9 and data.get("sub_type") == 16:
                    humidity = data.get(HubFields.HUMIDITY)
                    if humidity is not None:
                        humidity_value = float(humidity)
                        humidity_sensor = HumiditySensor(entity_id, description, humidity_value)
                        await self._async_add_or_update_sensor(humidity_sensor, humidity_value)

            await self._async_add_or_update_sensor(sensor, value)

        except Exception as err:
            _LOGGER.error("Error updating sensor: %s", err)

    async def _async_add_or_update_sensor(self, sensor: Any, value: Any) -> None:
        """Add or update a sensor."""
        unique_id = sensor.unique_id
        if unique_id not in self.sensors:
            if self.sensor_add_entities:
                self.sensor_add_entities([sensor])
                self.sensors[unique_id] = sensor
        else:
            self.sensors[unique_id].update_state(value)

    async def _async_update_climate(self, entity_id: str, data: dict[str, Any]) -> None:
        """Update or create climate entity."""
        from .climate import ComelitClimate

        description = data.get(HubFields.DESCRIPTION, "")

        try:
            measured_temp = float(format(float(data[HubFields.TEMPERATURE]), ".1f")) / 10
            target_temp = float(format(float(data[HubFields.TARGET_TEMPERATURE]), ".1f")) / 10
            
            # Parse auto_man value (1=auto, 2=manual, 5=off) - data comes as string
            auto_man = int(data.get("auto_man", 5))
            
            # Parse powerst (0=idle, 1=actively heating/cooling) - data comes as string
            powerst = int(data.get("powerst", 0))
            
            # Parse season
            is_winter = bool(int(data.get(HubFields.WINTER_SEASON, 0)))

            state_dict = {
                "auto_man": auto_man,
                "powerst": powerst,
                "is_winter_season": is_winter,
                "supports_cooling": _has_cooling_output(data),
                "measured_temperature": measured_temp,
                "target_temperature": target_temp,
            }

            if HubFields.HUMIDITY in data:
                state_dict["measured_humidity"] = float(data[HubFields.HUMIDITY])

            if entity_id not in self.climates:
                if self.climate_add_entities:
                    climate = ComelitClimate(entity_id, description, state_dict, self)
                    self.climate_add_entities([climate])
                    self.climates[entity_id] = climate
            else:
                self.climates[entity_id].update_state(state_dict)

        except Exception as err:
            _LOGGER.error("Error updating climate %s: %s", description, err)

    async def _async_update_light(self, entity_id: str, data: dict[str, Any]) -> None:
        """Update or create light entity."""
        from .light import ComelitLight

        description = data.get(HubFields.DESCRIPTION, "")

        try:
            # Dimmable light check
            brightness = None
            if data.get("type") == 3 and data.get("sub_type") == 4:
                brightness = int(data.get("bright", 0))

            state = STATE_ON if data.get("status") == "1" else STATE_OFF

            if entity_id not in self.lights:
                if self.light_add_entities:
                    light = ComelitLight(entity_id, description, state, brightness, self)
                    self.light_add_entities([light])
                    self.lights[entity_id] = light
            else:
                self.lights[entity_id].update_state(state, brightness)

        except Exception as err:
            _LOGGER.error("Error updating light: %s", err)

    async def _async_update_cover(
        self, entity_id: str, data: dict[str, Any], status_key: str
    ) -> None:
        """Update or create cover entity."""
        from .cover import ComelitCover

        description = data.get(HubFields.DESCRIPTION, "")

        try:
            if "position" in data:
                status = data.get("status", "0")
                if status == "0":
                    state = STATE_OPEN if data.get(status_key) == "1" else STATE_CLOSED
                elif status == "1":
                    state = STATE_OPENING
                elif status == "2":
                    state = STATE_CLOSING
                else:
                    state = STATE_UNKNOWN

                position = int(100 * float(data["position"]) / 255)
            else:
                state = STATE_UNKNOWN
                position = -1

            if entity_id not in self.covers:
                if self.cover_add_entities:
                    cover = ComelitCover(entity_id, description, state, position, self)
                    self.cover_add_entities([cover])
                    self.covers[entity_id] = cover
            else:
                self.covers[entity_id].update_state(state, position)

        except Exception as err:
            _LOGGER.error("Error updating cover: %s", err)

    async def _async_update_scenario(self, entity_id: str, data: dict[str, Any]) -> None:
        """Update or create scene entity."""
        from .scene import ComelitScenario

        description = data.get(HubFields.DESCRIPTION, "")

        try:
            if entity_id not in self.scenes:
                if self.scene_add_entities:
                    scene = ComelitScenario(entity_id, description, self)
                    self.scene_add_entities([scene])
                    self.scenes[entity_id] = scene

        except Exception as err:
            _LOGGER.error("Error updating scene: %s", err)

    async def _async_update_switch(self, entity_id: str, data: dict[str, Any]) -> None:
        """Update or create switch entity."""
        from .switch import ComelitSwitch

        description = data.get(HubFields.DESCRIPTION, "")

        try:
            state = STATE_ON if data.get(HubFields.STATUS) == "1" else STATE_OFF

            if entity_id not in self.switches:
                if self.switch_add_entities:
                    switch = ComelitSwitch(entity_id, description, None, self)
                    self.switch_add_entities([switch])
                    self.switches[entity_id] = switch
            else:
                self.switches[entity_id].update_state(state)

        except Exception as err:
            _LOGGER.error("Error updating switch: %s", err)

    # Command methods
    async def async_light_on(self, entity_id: str, brightness: int | None = None) -> None:
        """Turn on a light."""
        if brightness is None:
            act_params = [1]
            act_type = 0
        else:
            act_params = [brightness, -1]
            act_type = 11

        await self._async_publish({
            "req_type": RequestType.LIGHT,
            "req_sub_type": 3,
            "obj_id": entity_id,
            "act_type": act_type,
            "act_params": act_params,
        })

    async def async_light_off(self, entity_id: str) -> None:
        """Turn off a light."""
        await self._async_publish({
            "req_type": RequestType.LIGHT,
            "req_sub_type": 3,
            "obj_id": entity_id,
            "act_type": 0,
            "act_params": [0],
        })

    async def async_switch_on(self, entity_id: str) -> None:
        """Turn on a switch."""
        await self._async_publish({
            "req_type": RequestType.AUTOMATION,
            "req_sub_type": 3,
            "obj_id": entity_id,
            "act_type": 0,
            "act_params": [1],
        })

    async def async_switch_off(self, entity_id: str) -> None:
        """Turn off a switch."""
        await self._async_publish({
            "req_type": RequestType.AUTOMATION,
            "req_sub_type": 3,
            "obj_id": entity_id,
            "act_type": 0,
            "act_params": [0],
        })

    async def async_cover_up(self, entity_id: str) -> None:
        """Open a cover."""
        await self._async_publish({
            "req_type": RequestType.COVER,
            "req_sub_type": 3,
            "obj_id": entity_id,
            "act_type": 0,
            "act_params": [1],
        })

    async def async_cover_down(self, entity_id: str) -> None:
        """Close a cover."""
        await self._async_publish({
            "req_type": RequestType.COVER,
            "req_sub_type": 3,
            "obj_id": entity_id,
            "act_type": 0,
            "act_params": [0],
        })

    async def async_cover_position(self, entity_id: str, position: int) -> None:
        """Set cover position."""
        await self._async_publish({
            "req_type": RequestType.COVER,
            "req_sub_type": 3,
            "obj_id": entity_id,
            "act_type": 52,
            "act_params": [int(position * 255 / 100)],
        })

    async def async_climate_set_temperature(self, entity_id: str, temperature: float) -> None:
        """Set climate temperature."""
        await self._async_publish({
            "req_type": RequestType.TEMPERATURE,
            "req_sub_type": 3,
            "obj_id": entity_id,
            "act_type": 2,
            "act_params": [int(temperature * 10)],
        })

    async def async_climate_set_state(self, entity_id: str, hvac_mode: HVACMode) -> None:
        """Set climate HVAC mode (deprecated, use async_climate_set_mode)."""
        _LOGGER.warning("async_climate_set_state is deprecated, use async_climate_set_mode")
        if hvac_mode == HVACMode.OFF:
            await self.async_climate_set_mode(entity_id, 5)  # OFF
        else:
            await self.async_climate_set_mode(entity_id, 2)  # MANUAL

    async def async_climate_set_mode(self, entity_id: str, mode: int) -> None:
        """Set climate mode (1=auto, 2=manual, 5/6=off)."""
        # HSrv action types:
        # - act_type=0,  act_params=[0]    = OFF
        # - act_type=2,  act_params=[temp] = set temperature
        # - act_type=13, act_params=[mode] = switch clima mode, where mode is the
        #   target auto_man value (1=auto, 2=manual, 5=off_auto, 6=off_manual)

        if mode in (5, 6):  # OFF
            act_type = 0
            act_params = [0]
        elif mode in (1, 2):  # AUTO / MANUAL
            act_type = 13
            act_params = [mode]
        else:
            _LOGGER.error("Unknown climate mode: %s", mode)
            return

        _LOGGER.debug(
            "Climate command for %s: mode=%s act_type=%s act_params=%s",
            entity_id,
            mode,
            act_type,
            act_params,
        )

        await self._async_publish({
            "req_type": RequestType.TEMPERATURE,
            "req_sub_type": 3,
            "obj_id": entity_id,
            "act_type": act_type,
            "act_params": act_params,
        })

    async def async_climate_set_season(self, entity_id: str, is_winter: bool) -> None:
        """Set climate season (winter=heating, summer=cooling)."""
        # act_type 4 controls the season (est_inv)
        act_params = [1] if is_winter else [0]
        
        _LOGGER.debug(
            "Climate command for %s: season=%s",
            entity_id,
            "winter" if is_winter else "summer",
        )

        await self._async_publish({
            "req_type": RequestType.TEMPERATURE,
            "req_sub_type": 3,
            "obj_id": entity_id,
            "act_type": 4,
            "act_params": act_params,
        })

    async def async_activate_scenario(self, entity_id: str) -> None:
        """Activate a scenario."""
        await self._async_publish({
            "req_type": RequestType.SCENARIO,
            "req_sub_type": 3,
            "obj_id": entity_id,
            "act_type": 1000,
            "act_params": [],
        })


