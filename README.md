# Comelit SimpleHome and Comelit Vedo integration for Home Assistant

[![GitHub Release](https://img.shields.io/github/release/gicamm/homeassistant-comelit.svg?style=flat-square)](https://github.com/gicamm/homeassistant-comelit/releases)
[![GitHub Release](https://img.shields.io/github/commit-activity/y/gicamm/homeassistant-comelit.svg?style=flat-square)](https://github.com/gicamm/homeassistant-comelit/commits)
[![Test Coverage](https://img.shields.io/codecov/c/gh/gicamm/homeassistant-comelit?style=flat-square)](https://app.codecov.io/gh/gicamm/homeassistant-comelit/)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=gicamm_homeassistant-comelit&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=gicamm_homeassistant-comelit)
[![Code Smells](https://sonarcloud.io/api/project_badges/measure?project=gicamm_homeassistant-comelit&metric=code_smells)](https://sonarcloud.io/summary/new_code?id=gicamm_homeassistant-comelit)
[![Technical Debt](https://sonarcloud.io/api/project_badges/measure?project=gicamm_homeassistant-comelit&metric=sqale_index)](https://sonarcloud.io/summary/new_code?id=gicamm_homeassistant-comelit)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=gicamm_homeassistant-comelit&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=gicamm_homeassistant-comelit)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=gicamm_homeassistant-comelit&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=gicamm_homeassistant-comelit)
[![SonarQube Cloud](https://sonarcloud.io/images/project_badges/sonarcloud-light.svg)](https://sonarcloud.io/summary/new_code?id=gicamm_homeassistant-comelit)
[![License](https://img.shields.io/github/license/gicamm/homeassistant-comelit.svg?style=flat-square)](LICENSE)
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=gicamm&repository=homeassistant-comelit&category=integration)

Comelit SimpleHome and Comelit Vedo integration lets you connect your Home Assistant instance to Comelit Simple Home and
Vedo
systems.

For more information, see the [Wiki](https://github.com/gicamm/homeassistant-comelit/wiki).

### Installation

- Install
  using [HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=gicamm&repository=homeassistant-comelit&category=integration) (
  Or copy the contents of `custom_components/comelit/` to `<your config dir>/custom_components/comelit/`.)
- Restart Home Assistant
- Go to `Settings -> Devices & Services -> Add Integration`
- Search for `Comelit`
- Choose either:
  - `Comelit SimpleHome Hub`
  - `Comelit Vedo Alarm`
- Enter the required connection details in the UI

This integration is configured via the Home Assistant UI. YAML setup in `configuration.yaml` is no longer supported.

### Configuration and maintenance

After the integration is added, Home Assistant exposes three different flows:

- `Options`
  - Change runtime settings such as `scan_interval`
  - Enable temporary detailed climate debug logging for troubleshooting
- `Reconfigure`
  - Change connection settings such as host, port, serial, or MQTT client details
- `Reauthenticate`
  - Update credentials after an authentication failure without removing and re-adding the integration

### Polling and scan interval

The integration uses local polling. Comelit Hub communicates over MQTT, but the integration sends request/response
status requests instead of relying on unsolicited push updates. Comelit Vedo is polled over HTTP.

The default `scan_interval` is suitable for normal use. Lower values can make Home Assistant show changes sooner, but
they also increase traffic to the panel and should be used only when the panel remains responsive.

Detailed climate debug logging is intended for temporary troubleshooting while confirming Comelit mode and season
behavior. Disable it after collecting logs to avoid noisy Home Assistant logs.

Comelit Vedo panels do not reliably expose a stable serial number or MAC address through the HTTP API used by this
integration. The config flow prevents duplicate entries by host address, while child entity unique IDs are based on the
Home Assistant config entry ID so entity IDs do not change when the host is reconfigured.

### Development and testing

This repository includes a dockerized Home Assistant and pytest environment in [`.devcontainer/`](./.devcontainer).

- Start Home Assistant for manual testing:

```bash
docker compose -f .devcontainer/docker-compose.yml up -d homeassistant
```

- Open Home Assistant at `http://localhost:8123`
- Run tests in the Linux pytest container:

```bash
docker compose -f .devcontainer/docker-compose.yml run --rm pytest pytest
```

- Run lint checks:

```bash
docker compose -f .devcontainer/docker-compose.yml run --rm pytest ruff check .
```

The checked-in dev config lives in [`.devcontainer/config/configuration.yaml`](./.devcontainer/config/configuration.yaml).
Runtime files generated by Home Assistant inside `.devcontainer/config/` are intentionally gitignored.

### How to find the hub serial?

#### Comelit app

- Open the Comelit app
- Scan for a new hub device (Or if it's already added to the app, check in 'Manage Devices' -> Comelit Hub -> Network Configuration -> ID)
- Copy the serial (Hub MAC Address) (remove all symbols and hsrv prefix, i.e. "HSRV 00:25:29:17:2D:C2" -> "002529172DC2")

For more information, see the [Wiki](https://github.com/gicamm/homeassistant-comelit/wiki).

### Supported features
- Lights
- Shutters
- Energy Production
- Energy Consumption
- Clima
- Temperature/Humidity
- Automation
- Scenario
- Alarm

The integration also exports the alarm sensor as a presence detector. It allows presence-based lights, scenes, and so
on.

#### Comelit scenario

The integration supports the comelit scenario. It exports the scenario as a scene. A scene can be useful for exporting
some VIP features (such as opening the door) which, otherwise, cannot be fully reachable through the Hub.

### Lovelace example

Below is an example with lovelace:

```yaml
- type: entities
  title: Test
  entities:

# lights
  - entity: light.comelit_light_garage
    name: Garage
  - entity: light.comelit_light_bathroom
    name: Bathroom

# power
  - entity: sensor.comelit_power_prod_ftv
    name: Production
  - entity: sensor.comelit_power_cons
    name: Consume

    # door lock
  - entity: scene.comelit_doorlock
    name: Door lock
    icon: mdi:key

    # switch
  - entity: switch.comelit_switch1
    name: Switch1

    # clima
  - entity: climate.comelit_bathroom
    name: Bathroom
  - entity: climate.comelit_living
    name: Living

    # humidity
  - entity: sensor.comelit_humidity_bathroom
    name: Bathroom
  - entity: sensor.comelit_humidity_living
    name: Living

    # temperature
  - entity: sensor.comelit_temperature_bathroom
    name: Bathroom
  - entity: sensor.comelit_temperature_living
    name: Living

    # shutters
  - entity: cover.comelit_living
    name: Living
  - entity: cover.comelit_kitchen_sx
    name: Kitchen

    # vedo Alarm
  - entity: binary_sensor.comelit_vedo_garage
    name: Garage
  - entity: alarm_control_panel.comelit_vedo_garage
    name: Garage

```
