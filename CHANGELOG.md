# Changelog

## 0.1.0-beta.2 — Fix false "Can't read Mammotion's start command"
- **Fixed a false repair issue on Home Assistant 2026.9.** It said Luba Scheduler could not read `mammotion.start_mow`'s fields. HA 2026.9 wraps entity-service schemas one layer deeper than earlier versions, and the drift check didn't look inside it. The check now reads both shapes, and the issue clears by itself after updating.

## 0.1.0-beta.1 — Read-only preview
- **Setup and options flows.** Pick the Mammotion mower; its activity, battery, RTK-fix, camera and zone entities are found from the device and bound by entity-registry id, so Mammotion's entity renames don't break them. Split the zones into groups A and B, pick the condition sensors and the gate (with its polarity). Thresholds, angle and spacing lists are options.
- **Read-only entities:** optimal and adverse conditions, per-group conditions, mower readiness, window close, hard stop and next mow angle, each with its individual terms as attributes. Cuts per group, angle, path spacing and cutting height are owner-set selects/number.
- **Repair issues** when a bound mower entity disappears (a zone rebuilt in the Mammotion app), when `mammotion.start_mow` gains or loses a field, or when one of these entities' ids is already taken.
- Still read-only: nothing commands the mower, notifies or writes the calendar.
