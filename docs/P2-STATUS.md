# Port status (P2 done; P3 shadow running)

The source of truth for the port is `ajbaldwin/homeassistant-config`:
- `docs/superpowers/specs/2026-09-27-luba-hacs-port-design.md` (Q4–Q10)
- the YAML being ported: `packages/luba/scripts.yaml` (`script.luba_orchestrator` + `script.luba_fsm_transition`) and `packages/luba/automations.yaml`
- the transition contract: `docs/luba_gen3_prd.md` / `docs/luba_fsm_transition_spec.md`

## Where things stand (2026-10-01)

- **P2 (engine) is done and merged**: PR #5, then #7 (after-sunset fix). 300 tests pass (HA 2026.9.4, Python 3.14, `bash tools/test.sh -q`).
- **Released:** `v0.2.0-beta.1` (#6) through `v0.2.0-beta.4` (#13), all pre-releases. beta.2 fixes the after-sunset cutoff check (below); beta.3 adds `luba.export_yaml_state`; beta.4 pins `start_mow` to Mammotion 0.6.12's fields (#12). **beta.4 installed 2026-10-01**; the `start_mow_drift` repair issue cleared.
- **P3 shadow started 2026-09-27 ~21:17** on the box, with beta.1. It is in shadow mode, and Options → Mode points the comparison at the YAML FSM. **beta.2 installed 2026-09-28 06:56**, loaded by an HA restart at 07:05 (the exit criterion's restart).
- **YAML fixes found by the port, merged in the config repo:** v3.1.48 (#204, M7: the zero-length calendar event; deployed 2026-09-27) and v3.1.49 (#205, the after-sunset cutoff; pulled 2026-09-27 21:30, loaded by the 09-28 07:05 restart).

### P3 daily review

Read the logbook for `Luba Scheduler` lines:
- `shadow: diverged from the YAML for 5 min — port X, YAML Y` opens an episode, and `shadow: agrees with the YAML again (S) after N min` closes it. Every episode needs an explanation. Expected ones:
  - carry-over and adopted-run completions are logged and counted by the port, not the YAML (M7, before v3.1.48 deployed);
  - YAML `Charging` counts as matching port `Paused`.
- `shadow: would call …` lines show what the port would have commanded.
- Query (read-only, on the box, `sqlite3 -readonly /config/home-assistant_v2.db`): `logbook_entry` events whose `shared_data` contains `Luba Scheduler`, joined `events` → `event_types` → `event_data`; the YAML path is `states` for the FSM input_select.

#### Review log
| Window | Divergences | Notes |
|---|---|---|
| 09-27 21:17 → 09-28 08:00 | none | Idle on both sides. 21:17 `reboot_recover` "dispatching schedule_day" after sunset is the bug beta.2 fixes (harmless: Sunday, no group). 07:08 restart on beta.2: "FSM Idle needs no reconciliation". No `would call` lines. |
| 09-28 08:00 → 08:48 | none | Mow day, Group A on overseed hold. Both skip it: port `schedule_day` at 08:45:00, YAML at 08:45:10; both stay Idle. The port's `would call` lines are the one-minute "Skipped (overseed)" calendar entry and the "No Mow Today" push, matching what the YAML sent. The port's hold (lawn_growth `mowing_allowed`) and the YAML's (its own toggle) agreed. A held day doesn't count toward the exit criterion. |
| 09-28 08:48 → 10-01 18:00 | none | Three mow days, all on overseed hold: 09-29 Group B, 09-30 Group A, 10-01 Group B. Each day both sides skip at 08:45:00. The port's `would call` lines are the one-minute "Skipped (overseed)" entry and the "No Mow Today" push, and the YAML wrote the same 08:45–08:46 entry to `calendar.lawn_care_mowing_log`. Both FSMs stayed Idle the whole window. 9 HA restarts, each followed by `reboot_recover: FSM Idle needs no reconciliation`. On 10-01 Mammotion 0.6.12 raised the `start_mow_drift` issue (shadow only logs it); beta.4 (#12) fixes it. No mow day counts toward the exit criterion yet; the restart criterion is met. |
- The exit criterion (design Q10): ≥ 10 days, ≥ 2 mow days per un-held group, ≥ 1 restart, every divergence explained. The season is ending (1× from Oct 15), so the design recommends shadowing into November and cutting over in spring.

## Done

| File | What |
|---|---|
| `engine/fsm.py` | The 11 states and the `LEGAL` transition table: the union of what the YAML intents write, minus `Charging` (review M5). A test pins it to exactly the pairs the intents write. |
| `fsm_writer.py` | `FsmWriter.transition()` is the only writer of `store.fsm.state` (AST-checked). Same state returns `noop`; an unknown or illegal target raises `TransitionRefused`; it saves the store before logging. |
| `dispatcher.py` | A FIFO `asyncio.Queue(50)` with a single worker. Chained intents are enqueued, never awaited. A refusal or any exception becomes `enter_error`. Overflow logs critical and raises the `queue_overflow` repair issue. |
| `commander.py` | The only caller of `mammotion.*` / `lawn_mower.*` (AST-checked). Before every `start`/`resume` attempt it re-reads the gate and the adverse sensor, and it refuses on `start_mow` drift. Shadow mode makes every call a logged no-op. Active mode is refused while any `automation.luba_*` is on. All 23 `start_mow` fields are pinned (Mammotion 0.6.12). |
| `notifier.py` | Best-effort notify and calendar calls (review M3); no-ops in shadow mode. A calendar event is never shorter than one minute (see M7 below). |
| `intents.py` | `Orchestrator`: all 21 intents. Waits (start/route verification, dock, cancel, readiness refresh) run on HA timers, not the event loop's clock. |
| `listeners.py` | The 18 automations, as listeners that only dispatch (AST-checked). |
| `config_flow.py` | Options menu adds **timing** (scheduler/rotation times, verify/attempt/reprompt/cancel/floor/offline/idle values, typed ints) and **mode** (shadow by default; active needs a confirmation and is refused while a YAML automation is on). |
| `strings.json` / `translations/en.json` | New steps, the new entities, and the `queue_overflow` / `yaml_still_active` issues. |
| `tests/world.py` | The fake world. It fakes `mammotion.start_mow`/`cancel_job` and `lawn_mower.start_mowing`/`dock`: calls are recorded, each has a default reaction on activity mode, task areas and charging, and a test can script overrides. It also fakes `notify` and `calendar.create_event`; the calendar uses HA's real schema. `settle()` advances HA time while an intent waits. |
| `tests/test_engine_*.py` | The Q9 must-haves and per-intent branches (the list is in `tests/TRACEABILITY.md`). |
| `tests/replay/` + `tests/test_replay.py` | 09-17 comes from the recorder: the port's FSM path matches the YAML's to within 5 s. 08-01, 08-13, 08-21 and 08-22 are reconstructed from the defect log, because the recorder had already purged them. |
| `shadow.py` | Shadow comparison. With the YAML FSM entity set in Options → Mode, `sensor.luba_state` shows `yaml_state`, `diverged` and `diverged_since`. A divergence that lasts 5 minutes gets a logbook line, and another when it clears. YAML `Charging` counts as equal to `Paused`. The 09-17 replay in shadow never diverges. |
| `services.py` | `luba.import_yaml_state` for the P4 cutover. It takes values, not entity ids, so the cutover script renders them from its own helpers with templates. Every field is optional and a re-run is idempotent. It refuses unless the mode is shadow. It restores the FSM through `FsmWriter.restore` (still the one writer) and then runs `reboot_recover`. `luba.export_yaml_state` is the rollback (design Q10): read-only, allowed in either mode, it returns the same fields as response data in the YAML helpers' formats (naive local datetimes, the epoch for "none", a resolved angle/spacing). Export → import changes nothing. |
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

1. P3: review the `shadow:` logbook lines daily; explain every divergence. A divergence that is a port bug gets a fix, a beta and a note here.
2. ~~Before P4: merge the config-repo scripts and release the export service in a beta.~~ **Done:** config repo #207 (merged 2026-09-28) and beta.3. What shipped: `luba.export_yaml_state` here; `packages/luba_port/luba_port.yaml` in the config repo holds `script.luba_port_cutover` (every import field a template over the YAML helper it replaces) and `script.luba_port_rollback` (export → those helpers, FSM included). Both refuse while any YAML automation is on or the mode isn't shadow; `luba-tests/test_port_cutover.py` pins the field ↔ helper mapping both ways.
3. P4 cutover (design Q10): evening, mower docked. `git status` in `/config` → disable the 18 `automation.luba_*` (do not delete) → import → repoint the lawn dashboard → Options → Mode → active (needs the confirmation, and is refused while a YAML automation is on) → watch the next 08:45.

### Known behaviour kept from the YAML
- A held job on a mow day waits for the fresh-start readiness floor (95 %), not the 20 % resume floor. `schedule_day` writes `Scheduled` over it and `prompt_user` gates on readiness. On a non-mow day, recovery resumes at 20 %. **Owner decision 2026-09-28: keep it.** A full battery makes it less likely that the job docks partway and finishes late, which matters more as the days shorten.

### Fixed after P2 (#7, beta.2)
- The start-cutoff checks compare against TODAY's cutoff. After sunset, `sun.sun`'s `next_setting` (and so the window close) is tomorrow's. `reboot_recover`'s missed-schedule check fired on a reload at 21:13 (live, harmless on a Sunday), and `conditions_recovered` read a post-sunset ready edge as in window. The same fix is YAML v3.1.49.

## Watch item

M7 is explained and fixed in both systems (YAML v3.1.48, deployed 2026-09-27). After the next app-started (adopted) mow, confirm that the YAML wrote its calendar entry and counted the cut. The port does the same in shadow, visible as `shadow: would call calendar.create_event` in the logbook.
