# Comelit Integration Refactor Plan

This plan is based on the current async/config-flow branch, the uncommitted work in the repository, local Docker verification, and a Home Assistant best-practices review.

## Goals

- Keep the move to async and config entries.
- Bring the integration in line with Home Assistant runtime and entity conventions.
- Stabilize runtime behavior before extending climate features further.
- Replace outdated tests with tests that match the current architecture.

## Current Assessment

### What was the right direction

- Moving from synchronous code to async APIs was the correct architectural direction.
- Moving from YAML setup to `config_flow` was the correct direction for Home Assistant.
- Adding modern entity metadata such as `device_class` and correct feature flags is the right direction.

### What is not finished yet

- Runtime recovery is incomplete, especially for MQTT disconnects and auth/session failures.
- Config entry setup error handling does not follow HA expectations.
- Entity metadata is still built around a custom base class instead of HA-native entity/device patterns.
- Some current climate changes are still experimental and should not be treated as final behavior.
- The test suite still mostly reflects the pre-async, pre-config-flow architecture.

## Priority Order

1. Stabilize integration lifecycle and runtime recovery.
2. Fix entity model and metadata according to HA conventions.
3. Freeze and validate climate behavior.
4. Update tests to the current architecture.
5. Clean up documentation and developer tooling.

## Phase 1: Runtime and Config Entry Stability

### 1.1 Setup failure handling

Files:
- `custom_components/comelit/__init__.py`
- `custom_components/comelit/config_flow.py`

Tasks:
- Replace `return False` during entry setup failures with HA-appropriate exceptions.
- Use `ConfigEntryNotReady` for transient connectivity problems.
- Use `ConfigEntryAuthFailed` where credentials or session validity fail.
- Ensure config flow validation checks not only broker reachability, but also whether the integration can actually authenticate far enough to be usable.

Acceptance:
- Temporary network problems cause HA to retry entry setup.
- Invalid credentials lead to a proper auth failure path.
- No silent dead-end entries after a successful config flow but failed runtime login.

### 1.2 MQTT reconnect and runtime recovery

Files:
- `custom_components/comelit/hub.py`

Tasks:
- Detect listener/process/publish failures as runtime connection failures, not just log events.
- Implement reconnect flow with resubscribe and re-authentication.
- Mark entities unavailable when connection is lost and restore availability after reconnect.
- Prevent background tasks from continuing in a misleading "connected" state after transport loss.
- Review whether the current queue/task split is still the simplest correct approach; keep it only if it materially improves behavior.

Acceptance:
- Killing MQTT connectivity does not leave the integration stuck permanently.
- After reconnect, updates resume without HA restart.
- Entities reflect availability correctly.

### 1.3 Vedo session correctness

Files:
- `custom_components/comelit/vedo.py`

Tasks:
- Fix arm/disarm flow so it uses the valid session cookie consistently.
- Audit `_async_login`, `_async_get`, `_async_logout`, and `_async_arm_disarm` for cookie ownership and lifetime.
- Handle expired-cookie recovery without reporting false success.

Acceptance:
- Arm/disarm uses the active authenticated session.
- Failures are surfaced correctly in logs and entity state.

## Phase 2: HA Entity Model Alignment

### 2.1 Remove generic custom `state` abstraction

Files:
- `custom_components/comelit/comelit_device.py`
- `custom_components/comelit/climate.py`
- `custom_components/comelit/light.py`
- `custom_components/comelit/cover.py`
- `custom_components/comelit/switch.py`
- `custom_components/comelit/sensor.py`
- `custom_components/comelit/alarm_control_panel.py`
- `custom_components/comelit/binary_sensor.py`

Tasks:
- Stop relying on a generic base `state` property in `ComelitDevice`.
- Let each HA entity domain expose its state through native HA properties (`is_on`, `hvac_mode`, `native_value`, `alarm_state`, etc.).
- Keep the base class minimal: identifiers, availability, shared device info helpers.

Acceptance:
- No entity depends on the generic base `state` property for HA behavior.
- Domain entities follow HA-native APIs directly.

### 2.2 Device registry and naming

Files:
- `custom_components/comelit/comelit_device.py`
- all entity platform files

Tasks:
- Add `device_info` so entities are grouped into real devices in HA.
- Decide the device model:
  - one Hub service/device with child entities, and
  - one Vedo service/device with child entities,
  - or a more granular mapping if the protocol supports unique physical device identity.
- Use `has_entity_name = True` where appropriate.
- Stop hardcoding full display names into every entity name if HA can derive them from device + entity name.

Acceptance:
- Entities appear under proper devices in HA.
- Naming in HA UI follows modern conventions and is not duplicated.

### 2.3 Manifest and metadata cleanup

Files:
- `custom_components/comelit/manifest.json`

Tasks:
- Change `iot_class` from `local_push` to the correct polling-based value unless the integration is truly push-driven.
- Recheck versioning and requirements consistency against the actual runtime model.

Acceptance:
- Manifest behavior description matches reality.

## Phase 3: Platform-Specific Entity Fixes

### 3.1 Light behavior

Files:
- `custom_components/comelit/hub.py`
- `custom_components/comelit/light.py`

Tasks:
- Update brightness on every relevant incoming update, not only on entity creation.
- Verify brightness value scaling matches Home Assistant expectations.
- Keep `supported_color_modes` and `color_mode` aligned with actual capabilities.

Acceptance:
- Dimmable lights reflect real brightness changes in HA after updates.

### 3.2 Cover behavior

Files:
- `custom_components/comelit/cover.py`
- `custom_components/comelit/hub.py`

Tasks:
- Keep the `device_class` and supported feature improvements.
- Recheck current position inversion logic against real device semantics.
- Confirm stop behavior is actually correct for the protocol, not just inferred.

Acceptance:
- UI commands and reported position match device reality.

### 3.3 Sensor and icon review

Files:
- `custom_components/comelit/sensor.py`
- `custom_components/comelit/binary_sensor.py`
- `custom_components/comelit/switch.py`

Tasks:
- Keep `device_class` improvements where they map correctly.
- Use icons only where device class does not already provide the correct HA-native presentation.
- Review unit and value types to ensure they are native-value compliant.

Acceptance:
- Sensor rendering in HA is driven primarily by device class and native value metadata.

## Phase 4: Climate Rework Freeze

This phase should start only after Phases 1 and 2 are stable.

Files:
- `custom_components/comelit/hub.py`
- `custom_components/comelit/climate.py`
- `AiHelper.md`

Tasks:
- Separate protocol facts from hypotheses.
- Do not keep "theory" behavior in production code unless it is clearly guarded and validated.
- Reconfirm mode mapping:
  - off
  - manual
  - auto
  - season switching
  - target temperature writes
- Validate HA-facing semantics:
  - `hvac_mode`
  - `hvac_action`
  - `preset_mode`
  - supported features
- Decide whether exposing both HVAC mode and preset mode is the clearest UX for Comelit semantics.

Acceptance:
- Climate behavior is protocol-confirmed, not inferred.
- UI state matches actual device behavior.
- No climate command path is based solely on comments like "needs testing" or "theory".

## Phase 5: Test Suite Modernization

Files:
- `tests/test_init.py`
- `tests/test_hub.py`
- `tests/test_alarm_control_panel.py`
- `tests/test_cover.py`
- `tests/test_light.py`
- `tests/test_vedo.py`
- plus any new fixtures/helpers

Tasks:
- Remove tests that target old YAML setup and `setup_platform`.
- Replace them with tests for:
  - `async_setup_entry`
  - config entry lifecycle
  - reconnect and unavailable handling
  - entity creation/update behavior
  - climate command mapping
  - Vedo arm/disarm flow
- Use the Docker/Linux test path as the canonical local test route if Windows remains unreliable for HA deps.

Acceptance:
- Tests cover the current architecture, not the removed one.
- `pytest` can run locally via Docker and in CI with the same assumptions.

## Phase 6: Documentation and Dev Workflow

Files:
- `README.md`
- `AiHelper.md`
- `.devcontainer/docker-compose.yml`
- `.devcontainer/config/configuration.yaml`
- `requirements.txt`

Tasks:
- Update README from YAML-only instructions to config-flow usage.
- Keep protocol notes in `AiHelper.md`, but clearly separate confirmed findings from experiments.
- Document the Docker-based HA runtime path and Docker-based pytest path.
- Keep runtime Python requirements aligned with code imports.

Acceptance:
- A developer can run HA locally and run tests without guessing which path is current.

## Recommended Execution Sequence

### Iteration 1

- Phase 1.1
- Phase 1.2
- Phase 1.3

### Iteration 2

- Phase 2.1
- Phase 2.2
- Phase 2.3

### Iteration 3

- Phase 3.1
- Phase 3.2
- Phase 3.3

### Iteration 4

- Phase 4

### Iteration 5

- Phase 5
- Phase 6

## Immediate Next Step

Start with Phase 1.1 and 1.2:

- fix config entry failure semantics,
- then fix MQTT reconnect/unavailable handling.

That gives the biggest improvement in Home Assistant correctness with the lowest protocol risk.
