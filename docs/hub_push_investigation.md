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
