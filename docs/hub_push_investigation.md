# Comelit Hub Push Investigation

Goal: determine whether Comelit Hub over MQTT/TCP sends complete unsolicited state updates without Home Assistant sending status requests.

Procedure:

1. Enable temporary Hub payload debug in a local branch.
2. Connect Home Assistant to the Hub and wait for the initial login/status cycle.
3. Pause scheduled status requests or set a long scan interval.
4. Physically change each supported Hub domain:
   - light
   - cover/shutter
   - climate
   - power meter
   - switch/automation
   - scene/scenario if observable
5. Capture incoming MQTT payloads without calling `_async_update_status()`.
6. Record whether each physical change produced a complete payload that can update the matching Home Assistant entity.

Decision:

- Keep polling if any supported domain does not emit complete unsolicited updates.
- Keep polling if unsolicited updates require a prior status request to stay subscribed or fresh.
- Consider reducing polling to watchdog-only only if every supported domain emits complete, reliable unsolicited updates.

## Result (2026-06-11, verified on a real hub)

**The Comelit Hub does not broadcast unsolicited state updates.** All traffic on the `HSrv/<serial>/tx/<client>` topic
is a response to an explicit request published on the matching `rx` topic. Physical state changes (wall switches, the
Comelit app) produce no MQTT message until the next status request.

Polling is therefore the only correctness mechanism and must not be reduced to a watchdog.

### Beware of the shared-topic illusion

During verification, a test instance appeared to receive instant "push" updates. The cause: a second Home Assistant
instance (production, old integration, 1 s poll interval) was connected to the same hub with the same MQTT client ID
(`homeassistant`), so both instances shared the `tx` topic and the test instance was consuming status responses
triggered by the production instance's polling. Any future push observation must be done with **no other client using
the same client ID**, otherwise the results are invalid.
