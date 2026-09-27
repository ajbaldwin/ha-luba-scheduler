# P2 (engine): work-in-progress status

Branch `feat/p2-engine`. The source of truth for the port is `ajbaldwin/homeassistant-config`:
- `docs/superpowers/specs/2026-09-27-luba-hacs-port-design.md` (Q4–Q10)
- the YAML being ported: `packages/luba/scripts.yaml` (`script.luba_orchestrator` + `script.luba_fsm_transition`) and `packages/luba/automations.yaml`, PRD v3.1.47
- the transition contract: `docs/luba_fsm_transition_spec.md`

## Done (written; 106 P1 tests still pass; the new code has no tests yet)

| File | What |
|---|---|
| `engine/fsm.py` | The 11 states and the `LEGAL` transition table: the union of what the YAML intents actually write, minus `Charging` (review M5). |
| `fsm_writer.py` | `FsmWriter.transition()` is the only writer of `store.fsm.state`. Same state returns `noop`; an unknown or illegal target **raises** `TransitionRefused`; it saves the store *before* logging. |
| `dispatcher.py` | A FIFO `asyncio.Queue(50)` with a single worker. Chained intents are enqueued, never awaited. `TransitionRefused` or any other exception becomes an `enter_error` dispatch. Overflow raises a critical log line and a repair issue. |
| `commander.py` | The ONLY caller of `mammotion.*` / `lawn_mower.*`. It re-reads the gate (with polarity; unavailable counts as open) and the adverse sensor before every `start`/`resume`, and refuses on `start_mow` drift. In shadow mode every call is a logged no-op. It refuses active mode while any `automation.luba_*` is on. All 22 `start_mow` fields are pinned (`FIXED_JOB`); the 6 the YAML never sent use the schema defaults, so behaviour is unchanged. |
| `notifier.py` | Best-effort notify and calendar calls (review M3); no-ops in shadow mode. |
| `intents.py` | `Orchestrator`: all 21 intents ported (23 YAML intents minus `charge_threshold_reached` / `charging_timer_expired`). |
| `listeners.py` | The 18 thin automations, as listeners that only dispatch. #12 (the gate-zone crossing alert) notifies directly, as in the YAML. |
| `engine/rotation.py` | Weekly rotation: `next_in`, plus the seasonal height and cuts-per-group tables, verbatim from YAML. |
| `sensor.py` etc. | New entities: `sensor.luba_state` (enum; session fields as attributes), `sensor.luba_group_{a,b}_cuts`, `switch.luba_auto_start`, `button.luba_clear_error`. |
| `const.py` / `store.py` | Mode (`shadow` default), timing options, action ids, hardware modes. Store: `day.evaluated_at` (the renamed `scheduled_for`) and `settings.auto_start`. |

### Deliberate differences from the YAML (put them in the PR description)

- `Charging` state removed (M5). A docked held job is `Paused` with `charging` on. `close_window` gains a branch: `Paused` + charging + abort reason writes "Skipped (reason)" and goes to Idle. A `MODE_CHARGING` reading logs a warning and changes nothing.
- `_suspended` means the mode is `MODE_PAUSE` or `MODE_PAUSED` (the `MODE_CHARGING` clause is dropped).
- `start_mow` ignores a dispatch unless the FSM is `Awaiting Acknowledgment`. The YAML would have written `Starting` from any state; here that is illegal and would raise.
- Notification actions are `LUBA_START|SNOOZE|SKIP|RESUME:<prompt_id>`, plus `LUBA_CLEAR_ERROR` and `LUBA_TOGGLE_AUTO`. A tap on a stale nonce gets a "That prompt has expired" reply.
- Transitions raise instead of returning a status (review M2), and `verify_failed` / `fsm_unreadable` disappear.
- `held_group` compares live task-area sensors (switch unique_id + `_task_area`) against the bound zones, not an entity-id regex.
- Session and scheduled-group values are attributes of `sensor.luba_state`, not separate sensors (design Q2 listed `sensor.luba_session` and `sensor.luba_scheduled_group`).
- `reboot_recover` runs from `async_at_started`, which also means it runs on every reload of the integration.

## To do, in order

1. **Options and strings.** Add options-menu steps `timing` (scheduler/rotation time via TimeSelector, start verify/attempts, route verify, reprompt, cancel timeout, resume floor, offline, idle reconcile) and `mode` (shadow/active, with a warning). Add translations for:
   - the new entities: `state`, `group_a_cuts`, `group_b_cuts`, `auto_start`, `clear_error`;
   - the issues: `queue_overflow`, `yaml_still_active`.

   Copy `strings.json` to `translations/en.json`.
2. **Tests.** Fixtures:
   - a fake world that registers `mammotion.start_mow` / `cancel_job` and `lawn_mower.start_mowing` / `dock` (recording calls and mutating the activity/task-area states by a script);
   - a fake `notify.*` service;
   - a fake `calendar.create_event`.

   Must-have tests, from design Q9:
   - the FSM table allows every pair the intents write and nothing else;
   - an AST check that only `fsm_writer.py` assigns `fsm.state`, and only `commander.py` names mower service domains;
   - the gate flips open between start attempts 1 and 2, so no second command is sent (H1); adverse conditions refuse a start (M1);
   - both queue orderings of `schedule_day` + `conditions_recovered(floor)` at 08:45 give exactly one prompt;
   - a restart mid-session, mid-abort and mid-prompt loses nothing;
   - a re-slugged zone switch still gets its new entity_id sent;
   - shadow mode never calls a real service;
   - active mode is refused while a YAML automation is on;
   - a stale prompt nonce is rejected.
3. **Replay tests** from the recorder: 08-01 heat abort + resume; 08-13; 08-21 carryover + re-slug; 08-22 reboot; 09-17 (M7, once explained).
4. **`tests/TRACEABILITY.md`**: map every `luba-tests` function to a port test, or to "retired (reason)".
5. **Shadow comparison.** Add a `yaml_state` + `diverged` attribute on `sensor.luba_state`, read from `input_select.lawn_care_mower_state`, then `luba.import_yaml_state` (design Q4, P4).
6. PR → release `0.2.0-beta.1` → P3 shadow on the box.
