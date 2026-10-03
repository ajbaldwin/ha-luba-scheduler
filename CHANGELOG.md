# Changelog

## 0.2.0-beta.5 — Mammotion 0.6.14 support
- **Fixed: false "fields changed" repair with Mammotion 0.6.14+.** Mammotion 0.6.14 accepts `rain_tactics` on `mammotion.start_mow` again, so old automations keep working, but ignores its value. Luba Scheduler now treats it as a retired field: whether Mammotion's schema has it or not, it is not a change, and Luba still never sends it (sending it would raise Mammotion's own "Retired option used" repair). Starts are no longer refused in active mode.

## 0.2.0-beta.4 — Mammotion 0.6.11+ support
- **Updated for Mammotion 0.6.11+.** Mammotion removed `rain_tactics` from `mammotion.start_mow` and added `auto_change_direction` (auto-reverse mowing direction) and `ride_boundary_distance` (Edge Coverage). Luba Scheduler stops sending the first and pins both new ones off, which is Mammotion's own default, so routes are planned as before. The "fields changed" repair issue clears by itself after updating. Rain is still handled by Luba Scheduler's adverse abort; the mower's own rain detection switch now replaces the old plan-level setting.

## 0.2.0-beta.3 — Rollback export
- **New action: `luba.export_yaml_state`**, the rollback path. It returns Luba Scheduler's state (FSM, session, day, counters, settings) as response data, with the same fields `luba.import_yaml_state` takes, in the formats your existing helpers use. A rollback script writes them back into those helpers. It only reads, so it works in either mode. Export then import changes nothing.

## 0.2.0-beta.2 — No night-time scheduling after a restart
- **Fixed: a restart after sunset could schedule the day at night.** After sunset the window close (sunset minus the cutoff) rolls over to tomorrow's, so "still before today's cutoff" read as true all night. A reload or restart after sunset on a mow day then scheduled the day, and the next morning swept it away. A ready edge after sunset could likewise offer a held job. Both checks now require today's cutoff. Nothing ever started at night (optimal needs daylight), but it caused spurious notifications and a stray Scheduled state.

## 0.2.0-beta.1 — The engine, in shadow mode
- **The scheduler engine.** Luba Scheduler now runs the whole mowing day. It schedules the day's zone group, prompts on your phone (Start / Delay / Skip) or starts by itself when auto-start is on, verifies that the mower really started and planned a route, and follows telemetry to completion. It then logs the mow to the calendar and counts the group's cut. Weather aborts and resumes, a dusk hard stop, restart recovery, the window close and the weekly settings rotation are included.
- **Installs in shadow mode.** It makes and logs every decision, but in shadow mode mower commands, notifications and calendar writes are no-ops. Your existing automation stays the only thing commanding the mower. Active mode (Options → Mode) needs a confirmation and is refused while any `automation.luba_*` is on.
- **Shadow comparison.** In Options → Mode, point it at your existing FSM entity. The State sensor then shows `yaml_state` and `diverged`, and a divergence that lasts 5 minutes is written to the logbook.
- **Safety.** Before every start or resume attempt it re-reads the gate and the danger conditions, and it never sends a second attempt into an open gate or a storm. A zone the mower rebuilt refuses a partial mow. It refuses to start if Mammotion's start command has changed.
- **New entities:** State (with the session and day as attributes), Group A/B cuts, an Auto-start switch and a Clear error button. **New options:** Timing and Mode. **New action:** `luba.import_yaml_state`, for cutover (shadow mode only).
- Prompts use their own actions (`LUBA_*`) with a nonce. A tap on an old prompt is answered "That prompt has expired".

## 0.1.0-beta.2 — Fix false "Can't read Mammotion's start command"
- **Fixed a false repair issue on Home Assistant 2026.9.** It said Luba Scheduler could not read `mammotion.start_mow`'s fields. HA 2026.9 wraps entity-service schemas one layer deeper than earlier versions, and the drift check didn't look inside it. The check now reads both shapes, and the issue clears by itself after updating.

## 0.1.0-beta.1 — Read-only preview
- **Setup and options flows.** Pick the Mammotion mower; its activity, battery, RTK-fix, camera and zone entities are found from the device and bound by entity-registry id, so Mammotion's entity renames don't break them. Split the zones into groups A and B, pick the condition sensors and the gate (with its polarity). Thresholds, angle and spacing lists are options.
- **Read-only entities:** optimal and adverse conditions, per-group conditions, mower readiness, window close, hard stop and next mow angle, each with its individual terms as attributes. Cuts per group, angle, path spacing and cutting height are owner-set selects/number.
- **Repair issues** when a bound mower entity disappears (a zone rebuilt in the Mammotion app), when `mammotion.start_mow` gains or loses a field, or when one of these entities' ids is already taken.
- Still read-only: nothing commands the mower, notifies or writes the calendar.
