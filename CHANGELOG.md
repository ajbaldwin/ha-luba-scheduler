# Changelog

## Unreleased
- **Setup and options flows.** Pick the Mammotion mower; its activity, battery, RTK-fix, camera and zone entities are found from the device and bound by entity-registry id, so Mammotion's entity renames don't break them. Split the zones into groups A and B, pick the condition sensors and the gate (with its polarity). Thresholds, angle and spacing lists are options.
- **Read-only entities:** optimal and adverse conditions, per-group conditions, mower readiness, window close, hard stop and next mow angle, each with its individual terms as attributes. Cuts per group, angle, path spacing and cutting height are owner-set selects/number.
- **Repair issues** when a bound mower entity disappears (a zone rebuilt in the Mammotion app), when `mammotion.start_mow` gains or loses a field, or when one of these entities' ids is already taken.
- Still read-only: nothing commands the mower, notifies or writes the calendar.
- Repository scaffold: CI (tests, scrub gate), hassfest and HACS validation, release tooling. The setup flow aborts; there is nothing to configure yet.
