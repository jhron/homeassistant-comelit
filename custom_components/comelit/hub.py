"""Comelit Hub async implementation."""
from __future__ import annotations

import asyncio
import json
import logging
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
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


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

        self.topic_rx = f"HSrv/{hub_serial}/rx/{client_name}"
        self.topic_tx = f"HSrv/{hub_serial}/tx/{client_name}"

        self._client: aiomqtt.Client | None = None
        self._connected = False
        self._listen_task: asyncio.Task | None = None
        self._process_task: asyncio.Task | None = None
        self._status_task: asyncio.Task | None = None
        self._message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

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

        _LOGGER.info("Initializing Comelit Hub: %s:%s serial=%s", hub_host, mqtt_port, hub_serial)

    async def async_connect(self) -> bool:
        """Connect to the MQTT broker."""
        try:
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

            # Start status update task
            self._status_task = self.hass.async_create_background_task(
                self._async_status_updater(), "comelit_hub_status"
            )

            _LOGGER.info("Connected to Comelit Hub")
            return True

        except aiomqtt.MqttError as err:
            _LOGGER.error("Failed to connect to MQTT broker: %s", err)
            return False

    async def async_disconnect(self) -> None:
        """Disconnect from the MQTT broker."""
        self._connected = False

        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        if self._process_task:
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass

        if self._status_task:
            self._status_task.cancel()
            try:
                await self._status_task
            except asyncio.CancelledError:
                pass

        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None

        _LOGGER.info("Disconnected from Comelit Hub")

    async def _async_listen(self) -> None:
        """Listen for MQTT messages and put them in queue."""
        try:
            async for message in self._client.messages:
                try:
                    # Parse JSON in executor to avoid blocking
                    payload = await self.hass.async_add_executor_job(
                        json.loads, message.payload.decode("utf-8")
                    )
                    # Put message in queue for processing (non-blocking)
                    await self._message_queue.put(payload)
                except json.JSONDecodeError as err:
                    _LOGGER.error("Failed to decode message: %s", err)
        except aiomqtt.MqttError as err:
            if self._connected:
                _LOGGER.error("MQTT connection lost: %s", err)

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

                # Yield control after each message
                await asyncio.sleep(0)

            except Exception as err:
                _LOGGER.exception("Error processing message: %s", err)

    async def _async_status_updater(self) -> None:
        """Periodically request status updates."""
        while self._connected:
            if self.sessiontoken:
                await self._async_update_status()
            await asyncio.sleep(self.scan_interval)

    async def _async_publish(self, data: dict[str, Any]) -> None:
        """Publish a message to the hub."""
        if not self._client:
            return

        data["seq_id"] = self.sequence_id
        data["agent_id"] = self.agent_id
        data["sessiontoken"] = self.sessiontoken

        try:
            await self._client.publish(self.topic_rx, json.dumps(data))
            self.sequence_id += 1
        except aiomqtt.MqttError as err:
            _LOGGER.error("Failed to publish message: %s", err)

    async def _async_dispatch(self, payload: dict[str, Any]) -> None:
        """Dispatch incoming messages."""
        req_type = payload.get("req_type")

        if req_type == RequestType.ANNOUNCE:
            await self._async_handle_announce(payload)
        elif req_type == RequestType.LOGIN:
            self._handle_token(payload)
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
        _LOGGER.debug("Received session token")

    def _handle_parameters(self, payload: dict[str, Any]) -> None:
        """Handle parameters response."""
        # Parameters handling - kept for compatibility
        pass

    async def _async_update_status(self) -> None:
        """Request status update."""
        await self._async_publish({
            "req_type": RequestType.STATUS,
            "req_sub_type": -1,
            "obj_id": "GEN#17#13#1",
            "detail_level": 1,
        })

    async def _async_handle_status(self, payload: dict[str, Any]) -> None:
        """Handle status response."""
        try:
            elements = payload["out_data"][0][HubFields.ELEMENTS]
            await self._async_update_entities(elements)
        except Exception as err:
            _LOGGER.error("Error handling status: %s", err)

    async def _async_update_entities(self, elements: list[dict[str, Any]]) -> None:
        """Update entities from status response."""
        for item in elements:
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

            # Yield control to event loop to prevent blocking
            await asyncio.sleep(0)

    async def _async_update_sensor(self, entity_id: str, data: dict[str, Any]) -> None:
        """Update or create sensor entity."""
        from .sensor import PowerSensor, TemperatureSensor, HumiditySensor

        description = data.get(HubFields.DESCRIPTION, "")

        try:
            if HubClasses.POWER_CONSUMPTION in entity_id or HubClasses.FTV in entity_id:
                value = format(float(data[HubFields.INSTANT_POWER]), ".2f")
                prod = data.get(HubFields.PRODUCTION) == "1"
                sensor = PowerSensor(entity_id, description, value, prod)
            else:
                value = float(format(float(data[HubFields.TEMPERATURE]), ".1f")) / 10
                sensor = TemperatureSensor(entity_id, description, value)

                # Add humidity sensor if available
                if data.get("type") == 9 and data.get("sub_type") == 16:
                    humidity = data.get(HubFields.HUMIDITY)
                    if humidity is not None:
                        humidity_sensor = HumiditySensor(entity_id, description, humidity)
                        await self._async_add_or_update_sensor(humidity_sensor, humidity)

            await self._async_add_or_update_sensor(sensor, value)

        except Exception as err:
            _LOGGER.error("Error updating sensor: %s", err)

    async def _async_add_or_update_sensor(self, sensor: Any, value: Any) -> None:
        """Add or update a sensor."""
        name = sensor.entity_name
        if name not in self.sensors:
            if self.sensor_add_entities:
                self.sensor_add_entities([sensor])
                self.sensors[name] = sensor
                _LOGGER.info("Added sensor: %s", name)
        else:
            self.sensors[name].update_state(value)

    async def _async_update_climate(self, entity_id: str, data: dict[str, Any]) -> None:
        """Update or create climate entity."""
        from .climate import ComelitClimate

        description = data.get(HubFields.DESCRIPTION, "")

        try:
            measured_temp = float(format(float(data[HubFields.TEMPERATURE]), ".1f")) / 10
            target_temp = float(format(float(data[HubFields.TARGET_TEMPERATURE]), ".1f")) / 10

            state_dict = {
                "is_enabled": int(data.get("auto_man", 0)) == 2,
                "is_winter_season": bool(int(data.get(HubFields.WINTER_SEASON, 0))),
                "status": bool(int(data.get(HubFields.STATUS, 0))),
                "measured_temperature": measured_temp,
                "target_temperature": target_temp,
            }

            if HubFields.HUMIDITY in data:
                state_dict["measured_humidity"] = float(data[HubFields.HUMIDITY])

            name = f"comelit_climate_{description.lower().replace(' ', '-')}"
            if name not in self.climates:
                if self.climate_add_entities:
                    climate = ComelitClimate(entity_id, description, state_dict, self)
                    self.climate_add_entities([climate])
                    self.climates[name] = climate
                    _LOGGER.info("Added climate: %s", name)
            else:
                self.climates[name].update_state(state_dict)

        except Exception as err:
            _LOGGER.error("Error updating climate: %s", err)

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
                    _LOGGER.info("Added light: %s", description)
            else:
                self.lights[entity_id].update_state(state)

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
                    _LOGGER.info("Added cover: %s", description)
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
                    _LOGGER.info("Added scene: %s", description)

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
                    _LOGGER.info("Added switch: %s", description)
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
        """Set climate HVAC mode."""
        if hvac_mode == HVACMode.HEAT:
            act_type = 4
            act_params = [1]
        elif hvac_mode == HVACMode.COOL:
            act_type = 4
            act_params = [0]
        else:  # OFF
            act_type = 0
            act_params = [0]

        await self._async_publish({
            "req_type": RequestType.TEMPERATURE,
            "req_sub_type": 3,
            "obj_id": entity_id,
            "act_type": act_type,
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


