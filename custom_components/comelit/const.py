"""Constants for the Comelit integration."""

DOMAIN = "comelit"

# Config entry types
CONF_DEVICE_TYPE = "device_type"
DEVICE_TYPE_HUB = "hub"
DEVICE_TYPE_VEDO = "vedo"

# Hub configuration
CONF_MQTT_USER = "mqtt_user"
CONF_MQTT_PASSWORD = "mqtt_password"
CONF_SERIAL = "serial"
CONF_CLIENT = "client"

# Platforms
PLATFORMS_HUB = ["sensor", "light", "cover", "scene", "switch", "climate"]
PLATFORMS_VEDO = ["binary_sensor", "alarm_control_panel"]

# Defaults
DEFAULT_MQTT_PORT = 1883
DEFAULT_MQTT_USER = "hsrv-user"
DEFAULT_CLIENT = "homeassistant"
DEFAULT_SCAN_INTERVAL = 1
DEFAULT_VEDO_PORT = 80

# Other
COVER_CLOSING_TIME = 30
