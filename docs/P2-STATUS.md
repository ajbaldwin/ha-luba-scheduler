# P2 (engine): status

Branch `feat/p2-engine`, draft PR ajbaldwin/ha-luba-scheduler#5. The source of truth for the port is `ajbaldwin/homeassistant-config`:
- `docs/superpowers/specs/2026-09-27-luba-hacs-port-design.md` (Q4–Q10)
- the YAML being ported: `packages/luba/scripts.yaml` (`script.luba_orchestrator` + `script.luba_fsm_transition`) and `packages/luba/automations.yaml`, at the P0 fix commit
- the transition contract: `docs/luba_fsm_transition_spec.md`

**Steps 1–5 are done. 297 tests pass** (HA 2026.9.4, Python 3.14, `bash tools/test.sh -q`). Next: the PR, `0.2.0-beta.1`, and P3 shadow on the box.

## Done

| File | What |
|---|---|
| `engine/fsm.py` | The 11 states and the `LEGAL` transition table: the union of what the YAML intents write, minus `Charging` (review M5). A test pins it to exactly the pairs the intents write. |
| `fsm_writer.py` | `FsmWriter.transition()` is the only writer of `store.fsm.state` (AST-checked). Same state returns `noop`; an unknown or illegal target raises `TransitionRefused`; it saves the store before logging. |
| `dispatcher.py` | A FIFO `asyncio.Queue(50)` with a single worker. Chained intents are enqueued, never awaited. A refusal or any exception becomes `enter_error`. Overflow logs critical and raises the `queue_overflow` repair issue. |
| `commander.py` | The only caller of `mammotion.*` / `lawn_mower.*` (AST-checked). Before every `start`/`resume` attempt it re-reads the gate and the adverse sensor, and it refuses on `start_mow` drift. Shadow mode makes every call a logged no-op. Active mode is refused while any `automation.luba_*` is on. All 22 `start_mow` fields are pinned. |
| `notifier.py` | Best-effort notify and calendar calls (review M3); no-ops in shadow mode. A calendar event is never shorter than one minute (see M7 below). |
| `intents.py` | `Orchestrator`: all 21 intents. Waits (start/route verification, dock, cancel, readiness refresh) run on HA timers, not the event loop's clock. |
| `listeners.py` | The 18 automations, as listeners that only dispatch (AST-checked). |
| `config_flow.py` | Options menu adds **timing** (scheduler/rotation times, verify/attempt/reprompt/cancel/floor/offline/idle values, typed ints) and **mode** (shadow by default; active needs a confirmation and is refused while a YAML automation is on). |
| `strings.json` / `translations/en.json` | New steps, the new entities, and the `queue_overflow` / `yaml_still_active` issues. |
| `tests/world.py` | The fake world. It fakes `mammotion.start_mow`/`cancel_job` and `lawn_mower.start_mowing`/`dock`: calls are recorded, each has a default reaction on activity mode, task areas and charging, and a test can script overrides. It also fakes `notify` and `calendar.create_event`; the calendar uses HA's real schema. `settle()` advances HA time while an intent waits. |
| `tests/test_engine_*.py` | The Q9 must-haves and per-intent branches (the list is in `tests/TRACEABILITY.md`). |
| `tests/replay/` + `tests/test_replay.py` | 09-17 comes from the recorder: the port's FSM path matches the YAML's to within 5 s. 08-01, 08-13, 08-21 and 08-22 are reconstructed from the defect log, because the recorder had already purged them. |
| `shadow.py` | Shadow comparison. With the YAML FSM entity set in Options → Mode, `sensor.luba_state` shows `yaml_state`, `diverged` and `diverged_since`. A divergence that lasts 5 minutes gets a logbook line, and another when it clears. YAML `Charging` counts as equal to `Paused`. The 09-17 replay in shadow never diverges. |
| `services.py` | `luba.import_yaml_state` for the P4 cutover. It takes values, not entity ids, so the cutover script renders them from its own helpers with templates. Every field is optional and a re-run is idempotent. It refuses unless the mode is shadow. It restores the FSM through `FsmWriter.restore` (still the one writer) and then runs `reboot_recover`. |
| `tests/TRACEABILITY.md` | All 290 `luba-tests` functions → a port test, or "retired (reason)". `tests/test_traceability.py` checks that every referenced test exists. |

### Bugs the new tests found (fixed on this branch)

- **Double re-prompt:** every heartbeat prompted twice. A fired ack deadline was forgotten, so the next snapshot treated it as "missed during downtime" and dispatched `reprompt` again.
- **Gate recovery (#11) was up to a minute late:** the closing gate was only noticed on the coordinator's next refresh. It now listens to the gate itself, and there is one gate reader (`LubaCoordinator.gate_closed`).
- **The first weekly rotation didn't advance:** an unset angle/spacing (shown as the first entry) rotated back to the first entry.
- **Waits ignored HA time:** they used the event loop clock. Now `async_call_later` plus a 1 s poll. The readiness refresh waits for the camera instead of sleeping 10 s.
- An attribute-only activity update no longer resets the offline/idle timers.

### Findings in the live YAML (not changed there; owner to decide)

- **M7 explained (the 09-17 completion that was never logged).** For an adopted run, `log_cut` sends `calendar.create_event` with start == end. The calendar schema rejects that with `vol.Invalid`. That is not a `HomeAssistantError`, so `continue_on_error` doesn't catch it, and the script stops right after its `system_log` line: no calendar entry, no notify, no `last_logged_cut` latch, no `count_group_cut`. The recorder shows exactly this at both progress crossings that day (14:38:48 Group B, 14:58:42 an ungrouped zone). Group B's cut was never counted. **YAML fix:** for the no-metrics case, set `end_date_time` to now + 1 minute, as the skip entries already do. The port writes a one-minute event, and its fake calendar enforces the real schema.
- **A held job on a mow day waits for 95 %, not the 20 % resume floor.** `schedule_day` writes `Scheduled` over a held (suspended) job. `prompt_user` then gates on readiness, which uses the fresh-start floor, so the prompt waits until the battery reaches 95 %. On a non-mow day, the recovery path resumes at 20 %. The port keeps the YAML behaviour.

### Deliberate differences from the YAML (for the PR description)

- `Charging` state removed (M5). A docked held job is `Paused` with `charging` on. `close_window` gains a branch: `Paused` + charging + abort reason writes "Skipped (reason)" and goes to Idle. A `MODE_CHARGING` reading logs a warning and changes nothing.
- `_suspended` means the mode is `MODE_PAUSE` or `MODE_PAUSED` (the `MODE_CHARGING` clause is dropped).
- `start_mow` ignores a dispatch unless the FSM is `Awaiting Acknowledgment`.
- Notification actions are `LUBA_START|SNOOZE|SKIP|RESUME:<prompt_id>`, plus `LUBA_CLEAR_ERROR` and `LUBA_TOGGLE_AUTO`. A tap on a stale nonce gets "That prompt has expired".
- Transitions raise instead of returning a status (review M2); `verify_failed` / `fsm_unreadable` disappear.
- `held_group` compares live task-area sensors (switch unique_id + `_task_area`) against the bound zones, not an entity-id regex.
- Session and scheduled-group values are attributes of `sensor.luba_state`, not separate sensors.
- `reboot_recover` runs from `async_at_started`, so it also runs on every reload of the integration.
- Calendar events are at least one minute long (M7). Adopted-run completions are logged and counted, where the YAML lost them.
- #12 (gate-zone alert) fires on any crossing from a Group A zone into a Group B zone. The YAML named one specific pair.
- The overseed hold comes from lawn_growth's `mowing_allowed` per group (owner decision 3). Unavailable counts as held.

## To do, in order

6. Mark PR #5 ready → owner review → release `0.2.0-beta.1` → P3 shadow on the box: set the YAML FSM entity in Options → Mode, and review the `shadow:` logbook lines daily.
7. At P4: a one-off script in the config repo calls `luba.import_yaml_state`, each field a template over the YAML helper it replaces (`fsm_state: "{{ states('<the YAML FSM input_select>') }}"`, …). `luba.export_yaml_state` for rollback (design Q10) is not written yet.

## Watch item (unchanged)

After the next real mow completes, read the orchestrator trace the same evening (review M7). M7's cause is now known (above); the trace would confirm the `vol.Invalid` on `calendar.create_event`.
