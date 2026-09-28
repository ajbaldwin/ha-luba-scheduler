# Traceability: luba-tests → port tests

Every test function in the YAML package's structural suite (`luba-tests/`, in the
private config repo, at the P0 fix commit) mapped to the port test that now carries
its invariant, or marked **retired** with the reason. Paths are under `tests/`.
Generated, then checked by `tests/test_traceability.py`: every referenced port test
must exist, and the row count must match.

Most of the YAML suite parsed the package and asserted on its text (a guard sits
before a write, a helper has no `initial:`). The port replaces those with
behaviour: a fake mower, phone and calendar (`tests/world.py`), whole-day
scenarios, and replays of real days (`tests/replay/`).

**290 functions**: 244 mapped to port tests, 45 retired (most with a port test that covers what replaced them), 1 covered structurally.


## `test_adverse_start_refusal.py`

| luba-tests | Port |
|---|---|
| `test_start_mow_refuses_under_adverse_before_the_starting_write` | `test_engine_safety.py::test_adverse_at_tap_refuses_without_starting` |
| `test_the_adverse_refusal_holds_rather_than_erroring` | `test_engine_safety.py::test_adverse_at_tap_refuses_without_starting` |
| `test_adverse_is_reread_before_every_start_command` | `test_engine_safety.py::test_adverse_between_attempts_no_second_command` |
| `test_optimal_is_deliberately_not_a_start_refusal` | `test_engine_details.py::test_a_manual_start_overrides_permission_not_danger` |
| `test_no_actionable_prompt_goes_out_under_adverse` | `test_engine_intents.py::test_adverse_prompt_holds_without_buttons`<br>`test_engine_recovery.py::test_recovery_under_adverse_holds_in_awaiting_without_buttons` |
| `test_prompt_user_checks_adverse_before_auto_start_and_after_arming_the_deadline` | `test_engine_recovery.py::test_adverse_blocks_auto_start_and_keeps_the_heartbeat` |
| `test_conditions_recovered_holds_after_the_fsm_write` | `test_engine_recovery.py::test_recovery_under_adverse_holds_in_awaiting_without_buttons` |
| `test_reason_names_recent_close_lightning` | `test_engine_recovery.py::test_adverse_reason_ladder` |
| `test_a_stale_close_strike_no_longer_mislabels_a_heat_abort` | `test_engine_recovery.py::test_adverse_reason_ladder` |
| `test_an_unreadable_strike_time_is_not_lightning` | `test_engine_recovery.py::test_adverse_reason_ladder` |
| `test_the_rest_of_the_ladder_is_unchanged` | `test_engine_recovery.py::test_adverse_reason_ladder` |
| `test_adverse_abort_uses_the_shared_ladder` | `test_engine_recovery.py::test_adverse_reason_ladder`<br>`test_replay.py::test_0801_heat_abort_then_unattended_resume` |

## `test_automations.py`

| luba-tests | Port |
|---|---|
| `test_eighteen_automations` | retired — the 18 automations are `listeners.py`, not an enumerable YAML list; each one's behaviour is tested in the rows below<br>`test_engine_invariants.py::test_listeners_only_dispatch` |
| `test_only_one_orchestrator_rule_exemption_remains` | `test_engine_invariants.py::test_listeners_only_dispatch`<br>`test_engine_intents.py::test_gate_zone_crossing_alert` |
| `test_automations_are_thin` | `test_engine_invariants.py::test_listeners_only_dispatch` |
| `test_non_exempt_call_only_orchestrator` | `test_engine_invariants.py::test_listeners_only_dispatch` |
| `test_action_router_filters` | `test_engine_safety.py::test_foreign_and_nonceless_actions`<br>`test_engine_safety.py::test_shadow_adopts_a_run_the_yaml_started` |
| `test_adverse_abort_watcher_has_periodic_recheck` | `test_engine_intents.py::test_adverse_tick_catches_a_run_started_into_danger` |
| `test_adverse_watcher_tick_is_gated_on_adverse` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count`<br>`test_engine_intents.py::test_adverse_tick_catches_a_run_started_into_danger` |
| `test_ack_timeout_watcher_dispatches_reprompt` | `test_engine_intents.py::test_snooze_rearms_the_deadline_and_reprompts_later`<br>`test_engine_restart.py::test_ack_deadline_passed_during_downtime_reprompts_once` |
| `test_recovery_watcher_has_a_scheduler_time_trigger` | `test_engine_races.py::test_the_real_time_trigger_fires_both_in_order` |
| `test_idle_reconcile_automation_is_debounced_and_thin` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count`<br>`test_replay.py::test_0917_follows_the_yaml_path_and_logs_what_it_lost` |
| `test_gate_notification_triggers_on_the_merged_group_b_zone` | `test_engine_intents.py::test_gate_zone_crossing_alert` |

## `test_entities.py`

| luba-tests | Port |
|---|---|
| `test_abort_reason_helper` | `test_engine_restart.py::test_restart_mid_abort_keeps_the_reason_and_resumes` |
| `test_charging_timers` | retired — no `Charging` state or charging timers (review M5)<br>`test_engine_invariants.py::test_no_charging_state` |
| `test_conditions_sensors_exist` | `test_entities.py::test_entity_ids_are_the_design_contract` |
| `test_window_close_sensor` | `test_entities.py::test_window_close_is_sunset_minus_cutoff` |
| `test_adverse_terms` | `engine/test_conditions.py::test_adverse_terms_trip`<br>`engine/test_conditions.py::test_adverse_terms_hold` |
| `test_darkness_term_defers_to_the_camera` | `engine/test_conditions.py::test_adverse_terms_trip`<br>`engine/test_conditions.py::test_adverse_terms_hold` |
| `test_optimal_still_requires_daylight_to_start` | `engine/test_conditions.py::test_optimal_terms_fail` |
| `test_gate_sensor_has_no_inverting_device_class` | retired — the gate's meaning is the polarity option, not a device class<br>`test_engine_details.py::test_gate_polarity` |
| `test_orchestrator_treats_gate_on_as_closed` | `test_engine_details.py::test_gate_polarity`<br>`test_engine_invariants.py::test_there_is_one_gate_reader` |
| `test_corrected_position_is_a_template_device_tracker` | retired — `device_tracker.luba_corrected_position` is not ported (design Q2: a pass-through; dashboards use the mower's own tracker) |
| `test_corrected_position_reads_the_mowers_own_tracker` | retired — `device_tracker.luba_corrected_position` is not ported (design Q2: a pass-through; dashboards use the mower's own tracker) |
| `test_corrected_position_fails_closed_on_an_unreadable_sensor` | retired — `device_tracker.luba_corrected_position` is not ported (design Q2: a pass-through; dashboards use the mower's own tracker) |
| `test_no_device_tracker_see_call_remains` | retired — `device_tracker.luba_corrected_position` is not ported (design Q2: a pass-through; dashboards use the mower's own tracker) |
| `test_idle_reconcile_helper` | `test_config_flow.py::test_options_timing_types_and_normalises` |
| `test_overseed_hold_toggles_exist_per_group` | retired — owner decision 3: lawn_growth's per-group `mowing_allowed` replaces the toggles<br>`test_engine_intents.py::test_overseed_hold_skips_the_day_once`<br>`test_engine_recovery.py::test_the_overseed_authority_is_read_per_group` |

## `test_fsm_helper.py`

| luba-tests | Port |
|---|---|
| `test_helper_fields` | retired — a property of the YAML script's shape, with no Python equivalent<br>`test_engine_writer.py::test_same_state_is_a_noop_without_a_log_line` |
| `test_helper_queue_settings` | retired — no script queue; one dispatcher worker<br>`test_engine_races.py::test_one_prompt_whichever_runs_first` |
| `test_helper_writes_fsm_exactly_three_times` | `test_engine_invariants.py::test_only_the_fsm_writer_assigns_fsm_state` |
| `test_helper_returns_responses` | retired — refusals raise instead of returning a status (review M2)<br>`test_engine_writer.py::test_illegal_transition_raises_and_becomes_an_error` |
| `test_orchestrator_never_writes_fsm` | `test_engine_invariants.py::test_only_the_fsm_writer_assigns_fsm_state` |
| `test_helper_never_uses_continue_on_error_on_write` | retired — a property of the YAML script's shape, with no Python equivalent<br>`test_engine_writer.py::test_refused_starting_sends_no_command` |

## `test_gate_retry_and_active_group.py`

| luba-tests | Port |
|---|---|
| `test_the_gate_is_reread_before_every_start_command` | `test_engine_safety.py::test_gate_opens_between_attempts_no_second_command` |
| `test_a_gate_opened_mid_retry_raises_error_and_stops` | `test_engine_safety.py::test_gate_opens_between_attempts_no_second_command` |
| `test_the_mid_retry_gate_check_fails_closed` | `test_engine_details.py::test_an_unreadable_gate_counts_as_open`<br>`test_engine_safety.py::test_gate_opens_between_attempts_no_second_command` |
| `test_start_mow_does_not_stamp_active_group_before_verifying` | `test_engine_details.py::test_a_refused_or_failed_start_stamps_no_group` |
| `test_start_mow_stamps_active_group_on_the_verified_branch_only` | `test_engine_details.py::test_a_refused_or_failed_start_stamps_no_group`<br>`test_engine_day.py::test_happy_day_prompt_start_complete_log_count` |
| `test_a_failed_route_check_stops_before_the_stamp` | `test_engine_details.py::test_a_refused_or_failed_start_stamps_no_group` |
| `test_the_verified_stamp_names_the_group_being_mowed` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count`<br>`test_engine_races.py::test_carryover_resumes_the_held_group_and_credits_it` |
| `test_a_late_healed_start_restamps_active_group` | `test_engine_intents.py::test_late_start_heals_error_to_running` |
| `test_every_session_exit_transition_is_found` | retired — a YAML site count; the port has one `_reconcile_active_group`<br>`test_engine_details.py::test_exits_reconcile_active_group_to_the_hardware` |
| `test_every_session_exit_reconciles_active_group` | `test_engine_details.py::test_exits_reconcile_active_group_to_the_hardware`<br>`test_engine_intents.py::test_close_window_finalises_a_weather_aborted_docked_job` |
| `test_exit_reconciles_use_the_shared_hardware_expression` | `test_engine_details.py::test_exits_reconcile_active_group_to_the_hardware` |
| `test_the_reconcile_keeps_only_a_held_jobs_group` | `test_engine_details.py::test_exits_reconcile_active_group_to_the_hardware` |
| `test_close_window_reconciles_only_after_a_successful_write` | `test_engine_writer.py::test_illegal_transition_raises_and_becomes_an_error`<br>`test_engine_writer.py::test_refused_skip_leaves_the_prompt_alone` |

## `test_intents.py`

| luba-tests | Port |
|---|---|
| `test_enter_error_implemented` | `test_engine_invariants.py::test_intent_enum`<br>`test_engine_intents.py::test_clear_error_from_the_button_and_the_notification` |
| `test_clear_error_implemented` | `test_engine_invariants.py::test_intent_enum`<br>`test_engine_intents.py::test_clear_error_from_the_button_and_the_notification` |
| `test_prompt_user_implemented` | `test_engine_invariants.py::test_intent_enum`<br>`test_engine_day.py::test_happy_day_prompt_start_complete_log_count` |
| `test_handle_action_implemented` | `test_engine_invariants.py::test_intent_enum`<br>`test_engine_safety.py::test_stale_prompt_nonce_is_rejected` |
| `test_start_mow_implemented` | `test_engine_invariants.py::test_intent_enum`<br>`test_engine_day.py::test_happy_day_prompt_start_complete_log_count` |
| `test_telemetry_sync_implemented` | `test_engine_invariants.py::test_intent_enum`<br>`test_replay.py::test_0917_follows_the_yaml_path_and_logs_what_it_lost` |
| `test_telemetry_offline_implemented` | `test_engine_invariants.py::test_intent_enum`<br>`test_engine_intents.py::test_offline_then_back_at_the_dock` |
| `test_charging_timer_intents_implemented` | retired — no `Charging` state or charging timers (review M5)<br>`test_engine_invariants.py::test_intent_enum` |
| `test_reprompt_implemented` | `test_engine_invariants.py::test_intent_enum`<br>`test_engine_intents.py::test_snooze_rearms_the_deadline_and_reprompts_later` |
| `test_gate_recover_implemented` | `test_engine_invariants.py::test_intent_enum`<br>`test_engine_safety.py::test_gate_open_at_tap_sends_nothing` |
| `test_conditions_recovered_implemented` | `test_engine_invariants.py::test_intent_enum`<br>`test_engine_races.py::test_one_prompt_whichever_runs_first`<br>`test_engine_restart.py::test_restart_mid_abort_keeps_the_reason_and_resumes` |
| `test_adverse_abort_implemented` | `test_engine_invariants.py::test_intent_enum`<br>`test_replay.py::test_0801_heat_abort_then_unattended_resume` |
| `test_abort_reason_is_sentence_case_and_keeps_its_degree_symbol` | `test_replay.py::test_0801_heat_abort_then_unattended_resume`<br>`test_engine_recovery.py::test_adverse_reason_ladder` |
| `test_adverse_abort_self_guards_on_conditions` | `test_engine_recovery.py::test_adverse_abort_self_guards` |
| `test_log_completion_is_the_fsm_finaliser_only` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count` |
| `test_log_cut_implemented` | `test_engine_intents.py::test_completion_is_logged_and_counted_once` |
| `test_log_cut_always_chains_the_counter` | `test_engine_intents.py::test_completion_is_logged_and_counted_once`<br>`test_replay.py::test_0917_follows_the_yaml_path_and_logs_what_it_lost` |
| `test_last_logged_cut_helper_survives_a_restart` | `test_engine_restart.py::test_restart_mid_session_loses_nothing` |
| `test_close_window_implemented` | `test_engine_intents.py::test_close_window_with_no_mow_logs_skipped` |
| `test_close_window_does_not_dock` | `test_engine_intents.py::test_close_window_leaves_a_running_mow_alone` |
| `test_hard_stop_implemented` | `test_engine_intents.py::test_hard_stop_docks_a_mower_still_out_at_dusk`<br>`test_engine_intents.py::test_hard_stop_that_does_not_take_is_an_error` |
| `test_rotate_settings_implemented` | `test_engine_intents.py::test_monday_rotation_advances_and_resets` |
| `test_reboot_recover_implemented` | `test_engine_restart.py::test_restart_mid_session_loses_nothing`<br>`test_engine_restart.py::test_restart_spanning_the_scheduler_time_keeps_the_day`<br>`test_engine_restart.py::test_restart_while_starting_is_an_error` |
| `test_rotate_settings_reads_options_live` | `test_engine_intents.py::test_monday_rotation_advances_and_resets`<br>`test_config_flow.py::test_options_tuning_validates_and_types` |
| `test_rtk_readiness_uses_fix_quality_allowlist` | `engine/test_conditions.py::test_ready_terms_fail`<br>`test_mammotion.py::test_derive_roles_matches_unique_ids_not_decoys` |
| `test_start_mow_passes_mowing_parameters` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count` |
| `test_lawn_guards_exclude_a_docked_mower` | `test_replay.py::test_0801_heat_abort_then_unattended_resume`<br>`test_engine_restart.py::test_restart_mid_abort_keeps_the_reason_and_resumes` |
| `test_resume_and_fresh_start_use_different_service_calls` | `test_replay.py::test_0801_heat_abort_then_unattended_resume`<br>`test_engine_day.py::test_happy_day_prompt_start_complete_log_count` |
| `test_start_retries_before_erroring` | `test_engine_safety.py::test_third_attempt_accepted`<br>`test_engine_safety.py::test_ignored_starts_retry_up_to_the_attempt_limit` |
| `test_start_attempts_helper_exists` | `test_config_flow.py::test_options_timing_types_and_normalises` |
| `test_returning_can_go_back_to_running` | `test_engine_invariants.py::test_table_is_exactly_what_the_intents_write` |
| `test_conditions_recovered_has_no_same_day_guard` | `test_engine_races.py::test_one_prompt_whichever_runs_first`<br>`test_engine_intents.py::test_resume_uses_the_lower_floor` |
| `test_conditions_recovered_respects_auto_start` | `test_engine_races.py::test_one_auto_start_whichever_runs_first` |
| `test_conditions_recovered_auto_start_gate_checks_all_safety_terms` | `test_engine_races.py::test_one_auto_start_whichever_runs_first`<br>`test_engine_recovery.py::test_recovery_under_adverse_holds_in_awaiting_without_buttons` |
| `test_conditions_recovered_recovery_gate_allowlist_is_pinned` | `test_engine_recovery.py::test_recovery_never_overrides_error_or_a_skip`<br>`test_engine_recovery.py::test_a_held_job_resumes_in_place` |
| `test_schedule_day_does_not_cancel_a_suspended_job` | `test_engine_races.py::test_one_prompt_whichever_runs_first` |
| `test_schedule_day_stale_sweep_spares_a_suspended_job` | `test_engine_races.py::test_one_prompt_whichever_runs_first`<br>`test_engine_intents.py::test_stale_carryover_is_swept_then_the_day_scheduled` |
| `test_is_resume_uses_the_suspended_predicate` | `test_engine_intents.py::test_resume_uses_the_lower_floor`<br>`test_replay.py::test_0813_docked_heat_abort_resumes_at_the_resume_floor` |
| `test_exhausted_resume_error_names_the_remedy` | `test_engine_recovery.py::test_an_exhausted_resume_names_the_remedy` |
| `test_conditions_recovered_floors_at_the_scheduler_time` | `test_engine_recovery.py::test_recovery_floors_at_the_scheduler_time_and_the_season` |
| `test_promotion_is_skipped_on_the_floor_tick` | `test_engine_races.py::test_one_prompt_whichever_runs_first` |
| `test_duplicate_start_dispatch_is_not_an_error` | `test_engine_recovery.py::test_duplicate_and_stale_dispatches_are_ignored` |
| `test_prompt_user_refuses_a_stale_dispatch` | `test_engine_recovery.py::test_duplicate_and_stale_dispatches_are_ignored` |
| `test_schedule_day_yields_to_a_recovery_in_flight` | `test_engine_races.py::test_one_prompt_whichever_runs_first` |
| `test_no_script_variable_is_compared_to_a_quoted_number` | retired — HA's `parse_result` round trip is a Jinja template trap (defect 19); the port has no templates and its options are typed ints<br>`test_config_flow.py::test_options_tuning_validates_and_types` |
| `test_mow_day_frequency_is_compared_numerically` | retired — HA's `parse_result` round trip is a Jinja template trap (defect 19); the port has no templates and its options are typed ints<br>`engine/test_schedule.py::test_group_for_matrix` |
| `test_rotation_membership_is_string_normalised` | retired — HA's `parse_result` round trip is a Jinja template trap (defect 19); the port has no templates and its options are typed ints<br>`test_engine_intents.py::test_monday_rotation_advances_and_resets` |
| `test_start_mow_pins_every_job_parameter` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count` |
| `test_start_mow_sources_the_angle_from_the_sensor` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count`<br>`test_entities.py::test_settings_selects_drive_the_angle` |
| `test_start_mow_still_defaults_the_mode_to_absolute` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count` |
| `test_an_out_of_range_cut_is_logged` | `engine/test_schedule.py::test_angle_beyond_schedule_is_flagged_not_absorbed` |
| `test_zone_groups_are_enumerated_not_derived` | retired — zones are bound by entity-registry id in the config flow (spike §1)<br>`test_config_flow.py::test_full_flow_binds_by_registry_id` |
| `test_excluded_zones_are_in_no_group` | `test_replay.py::test_0917_follows_the_yaml_path_and_logs_what_it_lost` |
| `test_schedule_day_stamps_the_zone_group` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count` |
| `test_the_group_stamp_precedes_the_scheduled_transition` | `test_engine_recovery.py::test_the_group_is_stamped_before_scheduled_is_visible` |
| `test_scheduled_group_helper_survives_a_restart` | `test_engine_restart.py::test_restart_mid_prompt_keeps_the_prompt_live` |
| `test_a_fresh_start_without_a_group_refuses` | `test_engine_recovery.py::test_a_fresh_start_without_a_group_refuses_before_starting` |
| `test_the_group_refusal_precedes_the_starting_transition` | `test_engine_recovery.py::test_a_fresh_start_without_a_group_refuses_before_starting` |
| `test_carryover_resume_notifies` | `test_engine_races.py::test_carryover_resumes_the_held_group_and_credits_it`<br>`test_replay.py::test_0821_carryover_resumes_past_a_rebuilt_zone_and_counts_the_held_group` |
| `test_the_counter_is_driven_by_progress_not_by_the_fsm` | `test_engine_intents.py::test_completion_is_logged_and_counted_once` |
| `test_count_group_cut_requires_the_job_to_be_todays_group` | `test_replay.py::test_0917_follows_the_yaml_path_and_logs_what_it_lost`<br>`test_engine_details.py::test_an_ungrouped_completion_names_the_real_work_area` |
| `test_count_group_cut_cannot_count_the_same_cut_twice` | `test_engine_intents.py::test_completion_is_logged_and_counted_once` |
| `test_the_latch_is_written_after_the_increment` | retired — the increment and the latch are one in-memory update, saved together; there is no window between them<br>`test_engine_intents.py::test_completion_is_logged_and_counted_once` |
| `test_count_group_cut_increments_the_right_group` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count`<br>`test_engine_races.py::test_carryover_resumes_the_held_group_and_credits_it` |
| `test_rotate_settings_resets_both_group_counters` | `test_engine_intents.py::test_monday_rotation_advances_and_resets` |
| `test_group_counters_survive_a_restart` | `test_engine_restart.py::test_restart_mid_session_loses_nothing` |
| `test_mowing_angles_are_defined_in_git` | retired — the angle list is an option, typed and validated<br>`test_config_flow.py::test_options_tuning_validates_and_types` |
| `test_every_angle_clears_the_avoided_fence_line` | retired — the angle list is owner configuration; the defaults are the YAML's list |
| `test_rotate_settings_no_longer_touches_angle_2` | `engine/test_schedule.py::test_angle_cut2_perpendicular_only_at_2x_or_more` |
| `test_enter_error_records_the_state_it_came_from` | `test_engine_intents.py::test_late_start_heals_error_to_running`<br>`test_engine_recovery.py::test_a_fresh_start_without_a_group_refuses_before_starting` |
| `test_enter_error_records_the_origin_before_writing_the_fsm` | `test_engine_writer.py::test_refused_error_write_sends_no_error_notification` |
| `test_clear_error_blanks_the_error_origin` | `test_engine_intents.py::test_clear_error_from_the_button_and_the_notification` |
| `test_a_healed_error_stamps_the_session` | `test_engine_intents.py::test_late_start_heals_error_to_running` |
| `test_error_origin_helper_exists_and_survives_a_restart` | `test_engine_restart.py::test_restart_mid_session_loses_nothing` |
| `test_a_verified_start_clears_the_error_origin` | `test_engine_intents.py::test_late_start_heals_error_to_running` |
| `test_start_mow_has_no_docked_restart_path` | `test_replay.py::test_0813_docked_heat_abort_resumes_at_the_resume_floor` |
| `test_session_helpers_survive_a_restart` | `test_engine_restart.py::test_restart_mid_session_loses_nothing` |
| `test_a_fresh_start_verifies_that_a_route_was_actually_planned` | `test_engine_intents.py::test_route_never_planned_is_an_error` |
| `test_the_route_check_escalates_rather_than_retrying` | `test_engine_intents.py::test_route_never_planned_is_an_error` |
| `test_the_route_check_is_skipped_for_a_resume` | `test_replay.py::test_0801_heat_abort_then_unattended_resume`<br>`test_engine_recovery.py::test_a_held_job_resumes_in_place` |
| `test_route_verify_helper_exists` | `test_config_flow.py::test_options_timing_types_and_normalises` |
| `test_recovery_holds_a_suspended_job_until_conditions_are_optimal` | `test_engine_recovery.py::test_recovery_holds_a_job_until_conditions_are_optimal` |
| `test_the_recovery_hold_comes_before_the_fsm_write` | `test_engine_recovery.py::test_recovery_holds_a_job_until_conditions_are_optimal` |
| `test_adoption_stamps_the_group_it_finds` | `test_engine_intents.py::test_adopted_manual_run_is_stamped_counted_and_logged` |
| `test_adoption_never_overwrites_a_stamped_group` | `test_replay.py::test_0917_follows_the_yaml_path_and_logs_what_it_lost`<br>`test_engine_safety.py::test_shadow_adopts_a_run_the_yaml_started` |
| `test_close_window_live_run_branch_precedes_the_no_mow_sweep` | `test_engine_recovery.py::test_close_window_leaves_an_unadopted_live_run_alone` |
| `test_close_window_live_run_branch_is_a_noop` | `test_engine_recovery.py::test_close_window_leaves_an_unadopted_live_run_alone` |
| `test_telemetry_idle_finalises_via_completed_then_log_completion` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count`<br>`test_engine_writer.py::test_every_state_change_has_exactly_one_logbook_line` |
| `test_telemetry_idle_default_is_a_noop` | `test_replay.py::test_0822_reboot_with_a_slow_mammotion_leaves_a_resting_fsm_alone` |
| `test_reboot_recover_reconciles_a_docked_ready_via_telemetry_idle` | `test_engine_recovery.py::test_a_reboot_after_the_job_finished_completes_it` |
| `test_telemetry_sync_no_longer_maps_mode_finished` | `test_engine_intents.py::test_mode_charging_is_logged_not_acted_on` |
| `test_count_group_cut_credits_the_mowed_group_not_the_stamp` | `test_engine_races.py::test_carryover_resumes_the_held_group_and_credits_it`<br>`test_replay.py::test_0821_carryover_resumes_past_a_rebuilt_zone_and_counts_the_held_group` |
| `test_reboot_recover_only_waits_for_hardware_when_reconciling_a_live_session` | `test_replay.py::test_0822_reboot_with_a_slow_mammotion_leaves_a_resting_fsm_alone` |
| `test_evaluate_readiness_refreshes_stale_mower_before_deciding` | `test_engine_recovery.py::test_readiness_refreshes_a_stale_camera_after_sunrise` |
| `test_evaluate_readiness_daylight_authority_is_the_mower_camera` | `engine/test_conditions.py::test_ready_terms_fail` |
| `test_schedule_day_overseed_hold_reads_the_per_group_toggle` | `test_engine_recovery.py::test_the_overseed_authority_is_read_per_group`<br>`test_engine_details.py::test_an_overseed_hold_leaves_the_other_groups_day_alone` |
| `test_schedule_day_overseed_hold_skips_before_scheduling` | `test_engine_intents.py::test_overseed_hold_skips_the_day_once` |
| `test_schedule_day_overseed_hold_writes_a_skip_entry_and_push` | `test_engine_intents.py::test_overseed_hold_skips_the_day_once` |
| `test_schedule_day_overseed_hold_never_touches_the_fsm` | `test_engine_intents.py::test_overseed_hold_skips_the_day_once` |
| `test_schedule_day_overseed_skip_is_deduplicated_within_a_day` | `test_engine_intents.py::test_overseed_hold_skips_the_day_once` |
| `test_active_group_helper_survives_a_restart` | `test_engine_restart.py::test_restart_mid_session_loses_nothing` |
| `test_start_mow_stamps_active_group` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count` |
| `test_telemetry_sync_stamps_active_group` | `test_engine_intents.py::test_adopted_manual_run_is_stamped_counted_and_logged` |
| `test_active_group_is_cleared_with_session_work_area` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count` |

## `test_orchestrator.py`

| luba-tests | Port |
|---|---|
| `test_intent_enum` | `test_engine_invariants.py::test_intent_enum`<br>`test_engine_recovery.py::test_every_intent_has_a_handler` |
| `test_orchestrator_fields` | retired — a property of the YAML script's shape, with no Python equivalent |
| `test_every_helper_call_uses_new_signature` | retired — a property of the YAML script's shape, with no Python equivalent |
| `test_no_stub_branches_remain` | `test_engine_recovery.py::test_every_intent_has_a_handler` |
| `test_continue_on_error_never_on_helper_calls` | retired — a property of the YAML script's shape, with no Python equivalent<br>`test_engine_writer.py::test_refused_scheduled_sends_no_prompt` |
| `test_package_fsm_write_total` | `test_engine_invariants.py::test_only_the_fsm_writer_assigns_fsm_state` |
| `test_every_intent_has_a_branch` | `test_engine_recovery.py::test_every_intent_has_a_handler` |
| `test_repeat_blocks_are_well_formed` | retired — a property of the YAML script's shape, with no Python equivalent |
| `test_suspended_predicate_is_hardware_derived` | `test_engine_races.py::test_one_prompt_whichever_runs_first`<br>`test_engine_recovery.py::test_a_held_job_resumes_in_place` |
| `test_orchestrator_declares_trigger_source` | `test_engine_races.py::test_one_prompt_whichever_runs_first` |

## `test_package_parses.py`

| luba-tests | Port |
|---|---|
| `test_yaml_parses` | retired — no YAML package<br>`test_scaffold.py::test_manifest`<br>`test_scaffold.py::test_translations_match_strings` |
| `test_scripts_present` | retired — no YAML package<br>`test_engine_invariants.py::test_intent_enum` |

## `test_render_semantics.py`

| luba-tests | Port |
|---|---|
| `test_parse_result_matches_home_assistant` | retired — HA's `parse_result` round trip is a Jinja template trap (defect 19); the port has no templates and its options are typed ints |
| `test_the_round_trip_defeats_string_coercion` | retired — HA's `parse_result` round trip is a Jinja template trap (defect 19); the port has no templates and its options are typed ints |
| `test_render_variables_threads_parsed_values_forward` | retired — HA's `parse_result` round trip is a Jinja template trap (defect 19); the port has no templates and its options are typed ints |
| `test_group_schedule_matrix` | `engine/test_schedule.py::test_group_for_matrix` |
| `test_is_mow_day_follows_the_group` | `engine/test_schedule.py::test_group_for_matrix`<br>`test_engine_intents.py::test_out_of_season_and_rest_days_do_nothing` |
| `test_the_two_groups_never_share_a_day` | `engine/test_schedule.py::test_groups_never_share_a_day_and_sunday_is_free` |
| `test_every_frequency_gives_both_groups_at_least_one_day` | `engine/test_schedule.py::test_groups_never_share_a_day_and_sunday_is_free` |
| `test_unparseable_frequency_schedules_nothing` | `engine/test_schedule.py::test_unknown_frequency_never_mows` |
| `test_frequency_accepts_any_numeric_spelling` | retired — HA's `parse_result` round trip is a Jinja template trap (defect 19); the port has no templates and its options are typed ints |
| `test_rotation_advances_exactly_one_step` | `engine/test_rotation.py::test_rotation_advances_exactly_one_step_around_the_cycle`<br>`test_engine_intents.py::test_monday_rotation_advances_and_resets` |
| `test_rotation_resets_to_start_on_genuine_drift` | `engine/test_rotation.py::test_an_unknown_current_value_restarts_at_the_first_entry` |
| `test_gap6_guard_is_quiet_for_every_in_sequence_value` | `engine/test_rotation.py::test_rotation_advances_exactly_one_step_around_the_cycle`<br>`test_engine_intents.py::test_monday_rotation_advances_and_resets` |
| `test_gap6_guard_still_fires_on_real_drift` | `test_engine_recovery.py::test_rotation_logs_a_drifted_setting` |
| `test_start_mow_sends_entity_ids_not_hashes` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count` |
| `test_start_mow_mows_only_the_stamped_group` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count` |
| `test_start_mow_area_guard_still_catches_an_unresolvable_switch` | `test_engine_safety.py::test_rebuilt_zone_refuses_a_partial_mow` |
| `test_area_guard_counts_against_the_resolved_list_not_a_literal` | `test_engine_safety.py::test_rebuilt_zone_refuses_a_partial_mow` |
| `test_area_guard_is_skipped_on_a_resume` | `test_replay.py::test_0821_carryover_resumes_past_a_rebuilt_zone_and_counts_the_held_group` |
| `test_an_unstamped_group_yields_no_areas_at_all` | `test_engine_recovery.py::test_a_fresh_start_without_a_group_refuses_before_starting` |
| `test_held_group_recognises_each_group` | `test_engine_details.py::test_dead_leftover_task_areas_do_not_hide_the_held_group`<br>`test_engine_races.py::test_carryover_resumes_the_held_group_and_credits_it`<br>`test_replay.py::test_0801_heat_abort_then_unattended_resume` |
| `test_held_group_is_empty_for_anything_else` | `test_engine_details.py::test_dead_leftover_task_areas_do_not_hide_the_held_group`<br>`test_engine_intents.py::test_adverse_abort_on_a_manual_run_docks_without_bookkeeping` |
| `test_next_mow_angle_matrix` | `engine/test_schedule.py::test_angle_cut1_uses_primary`<br>`engine/test_schedule.py::test_angle_cut2_perpendicular_only_at_2x_or_more`<br>`engine/test_schedule.py::test_angle_cut3_reuses_primary` |
| `test_the_perpendicular_is_exactly_ninety_degrees` | `engine/test_schedule.py::test_angle_cut2_perpendicular_only_at_2x_or_more` |
| `test_each_group_reads_its_own_counter` | `test_entities.py::test_settings_selects_drive_the_angle` |
| `test_an_unstamped_group_falls_back_to_the_first_cut` | `engine/test_schedule.py::test_angle_without_group_counts_zero_cuts` |
| `test_an_unknown_counter_falls_back_to_the_first_cut` | retired — the counters are typed ints in the store; there is no unknown state<br>`engine/test_schedule.py::test_angle_without_group_counts_zero_cuts` |
| `test_we_never_send_the_same_angle_twice_within_a_group_week` | `engine/test_schedule.py::test_angle_cut2_perpendicular_only_at_2x_or_more`<br>`engine/test_schedule.py::test_angle_cut3_reuses_primary` |
| `test_a_start_verification_error_heals_when_the_mower_reports_working` | `test_engine_intents.py::test_late_start_heals_error_to_running` |
| `test_an_error_from_any_other_origin_stays_latched` | `test_engine_intents.py::test_working_in_error_from_elsewhere_does_not_heal`<br>`test_engine_recovery.py::test_close_window_leaves_an_unadopted_live_run_alone` |
| `test_an_error_with_no_recorded_origin_stays_latched` | `test_engine_intents.py::test_working_in_error_from_elsewhere_does_not_heal` |
| `test_every_previously_admitted_state_still_transitions_to_running` | `test_engine_invariants.py::test_table_is_exactly_what_the_intents_write` |
| `test_a_mower_paused_on_the_lawn_still_resumes_in_place` | `test_engine_recovery.py::test_a_held_job_resumes_in_place` |
| `test_a_docked_suspended_job_is_now_treated_as_resumable` | `test_engine_recovery.py::test_a_held_job_resumes_in_place`<br>`test_replay.py::test_0813_docked_heat_abort_resumes_at_the_resume_floor` |
| `test_a_mower_holding_no_job_needs_no_resume_path` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count` |
| `test_a_docked_resume_falls_back_to_the_held_group` | `test_engine_recovery.py::test_a_held_job_resumes_in_place` |
| `test_a_stamped_group_wins_over_the_held_one` | `test_engine_races.py::test_carryover_resumes_the_held_group_and_credits_it` |
| `test_a_docked_resume_with_no_group_anywhere_resolves_to_nothing` | retired — as in the YAML, only a FRESH start is refused without a group (a resume sends no areas)<br>`test_engine_recovery.py::test_a_fresh_start_without_a_group_refuses_before_starting` |
| `test_a_docked_suspended_resume_floors_at_twenty_not_ninety_five` | `test_replay.py::test_0813_docked_heat_abort_resumes_at_the_resume_floor`<br>`test_engine_intents.py::test_resume_uses_the_lower_floor` |
| `test_the_tracker_follows_the_mower_not_the_reference_station` | retired — `device_tracker.luba_corrected_position` is not ported (design Q2: a pass-through; dashboards use the mower's own tracker) |
| `test_the_tracker_is_unavailable_rather_than_at_null_island` | retired — `device_tracker.luba_corrected_position` is not ported (design Q2: a pass-through; dashboards use the mower's own tracker) |
| `test_a_tracker_with_no_coordinates_is_unavailable` | retired — `device_tracker.luba_corrected_position` is not ported (design Q2: a pass-through; dashboards use the mower's own tracker) |
| `test_live_zones_ignores_sensors_that_are_merely_present` | `test_engine_details.py::test_dead_leftover_task_areas_do_not_hide_the_held_group` |
| `test_held_group_recognises_group_b_through_the_stale_leftovers` | `test_engine_details.py::test_dead_leftover_task_areas_do_not_hide_the_held_group` |
| `test_a_group_whose_own_sensors_are_dead_is_not_held` | `test_engine_recovery.py::test_a_group_whose_own_sensors_are_dead_is_not_held` |
| `test_live_zones_selects_each_group_including_the_outside_prefix` | retired — task-area sensors are derived from the bound switch's unique_id, so entity_id prefixes are irrelevant<br>`test_mammotion.py::test_task_area_sensor_is_derived_from_the_switch` |
| `test_route_is_verified_once_the_group_task_areas_go_live` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count` |
| `test_a_phantom_job_never_verifies` | `test_engine_intents.py::test_route_never_planned_is_an_error` |
| `test_the_previous_jobs_leftovers_do_not_verify_this_job` | `test_engine_recovery.py::test_previous_leftovers_do_not_verify_a_phantom_start` |
| `test_a_half_planned_route_does_not_verify` | `test_engine_details.py::test_a_half_planned_route_does_not_verify` |
| `test_an_unstamped_group_never_verifies` | `test_engine_recovery.py::test_a_fresh_start_without_a_group_refuses_before_starting` |
| `test_log_cut_desc_renders_with_an_aware_now` | `test_engine_invariants.py::test_no_naive_datetimes_in_the_integration`<br>`test_engine_day.py::test_happy_day_prompt_start_complete_log_count` |
| `test_close_window_live_run_predicate` | `test_engine_recovery.py::test_close_window_leaves_an_unadopted_live_run_alone`<br>`test_engine_intents.py::test_close_window_leaves_a_running_mow_alone` |
| `test_telemetry_idle_guard` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count`<br>`test_replay.py::test_0917_follows_the_yaml_path_and_logs_what_it_lost`<br>`test_engine_recovery.py::test_a_reboot_after_the_job_finished_completes_it` |
| `test_count_group_cut_grp_follows_the_mowed_zones_not_the_stamp` | `test_engine_races.py::test_carryover_resumes_the_held_group_and_credits_it` |
| `test_log_cut_area_names_the_mowed_group_not_a_stale_work_area` | `test_replay.py::test_0917_follows_the_yaml_path_and_logs_what_it_lost`<br>`test_replay.py::test_0821_carryover_resumes_past_a_rebuilt_zone_and_counts_the_held_group` |
| `test_log_cut_area_falls_back_when_no_group_matches` | `test_engine_details.py::test_an_ungrouped_completion_names_the_real_work_area`<br>`test_engine_details.py::test_junk_work_areas_become_manual` |
| `test_summary_group_completion_with_metrics` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count` |
| `test_summary_ungrouped_completion_uses_the_real_work_area` | `test_engine_details.py::test_an_ungrouped_completion_names_the_real_work_area` |
| `test_summary_manual_unknown_becomes_manual` | `test_engine_details.py::test_junk_work_areas_become_manual`<br>`test_replay.py::test_0917_follows_the_yaml_path_and_logs_what_it_lost` |
| `test_summary_adopted_no_metrics_omits_duration_and_trailing_comma` | `test_engine_intents.py::test_adopted_manual_run_is_stamped_counted_and_logged` |
| `test_log_key_latch_is_unaffected_by_the_title_rework` | `test_replay.py::test_0917_follows_the_yaml_path_and_logs_what_it_lost` |
| `test_skip_prefix_names_the_scheduled_group` | `test_engine_safety.py::test_skip_then_close_window_logs_skipped` |
| `test_skip_prefix_omits_the_label_when_nothing_was_scheduled` | `test_engine_details.py::test_a_skip_with_no_group_has_no_dangling_label` |
| `test_weather_abort_title_includes_the_group_and_the_reason` | `test_engine_intents.py::test_close_window_finalises_a_weather_aborted_docked_job` |
| `test_skip_titles_never_render_a_dangling_comma` | `test_engine_details.py::test_a_skip_with_no_group_has_no_dangling_label` |
| `test_skip_branches_now_write_a_calendar_entry` | `test_engine_safety.py::test_skip_then_close_window_logs_skipped`<br>`test_engine_intents.py::test_close_window_with_no_mow_logs_skipped` |
| `test_skipped_today_still_transitions_to_idle` | `test_engine_safety.py::test_skip_then_close_window_logs_skipped` |
| `test_no_mow_sweep_still_notifies` | `test_engine_intents.py::test_close_window_with_no_mow_logs_skipped` |
| `test_every_skip_calendar_entry_has_a_nonzero_duration` | covered structurally — every calendar write in the engine tests goes through Home Assistant's real `CREATE_EVENT_SCHEMA`, which rejects end <= start<br>`test_engine_intents.py::test_adopted_manual_run_is_stamped_counted_and_logged` |
| `test_mowed_today_either_latch_counts` | `test_replay.py::test_0822_an_error_at_close_after_a_mow_is_swept_silently` |
| `test_mowed_today_false_for_sentinels` | retired — typed store fields have no unknown/unavailable sentinel |
| `test_mowed_today_renders_as_a_real_boolean` | retired — HA's `parse_result` round trip is a Jinja template trap (defect 19); the port has no templates and its options are typed ints |
| `test_mowed_today_branch_shares_the_stranded_fsm_set` | `test_replay.py::test_0822_an_error_at_close_after_a_mow_is_swept_silently` |
| `test_mowed_today_branch_has_no_calendar_entry_or_no_mow_push` | `test_replay.py::test_0822_an_error_at_close_after_a_mow_is_swept_silently` |
| `test_mowed_today_branch_transitions_to_idle_and_clears_the_prompt_tag` | `test_replay.py::test_0822_an_error_at_close_after_a_mow_is_swept_silently` |
| `test_mowed_today_branch_response_variable_feeds_the_shared_error_check` | retired — no response variables; a refused write raises (review M2)<br>`test_engine_writer.py::test_illegal_transition_raises_and_becomes_an_error` |
| `test_mowed_today_branch_precedes_the_plain_sweep_and_follows_live_run` | `test_replay.py::test_0822_an_error_at_close_after_a_mow_is_swept_silently`<br>`test_engine_recovery.py::test_close_window_leaves_an_unadopted_live_run_alone` |
| `test_plain_sweep_regression_still_writes_skipped_entry_and_no_mow_push` | `test_engine_intents.py::test_close_window_with_no_mow_logs_skipped`<br>`test_engine_details.py::test_error_on_a_mow_day_without_a_mow_is_no_mow_today` |
| `test_overseed_hold_is_true_only_for_the_days_own_group` | `test_engine_details.py::test_an_overseed_hold_leaves_the_other_groups_day_alone` |
| `test_overseed_hold_is_false_when_the_toggle_is_off` | `test_engine_recovery.py::test_the_overseed_authority_is_read_per_group` |
| `test_overseed_hold_reads_group_b_toggle_for_a_group_b_day` | `test_engine_recovery.py::test_the_overseed_authority_is_read_per_group` |
| `test_overseed_skip_is_not_yet_recorded_when_the_window_is_from_another_day` | `test_engine_intents.py::test_overseed_hold_skips_the_day_once` |
| `test_overseed_skip_is_recorded_once_the_window_is_stamped_today` | `test_engine_intents.py::test_overseed_hold_skips_the_day_once` |
| `test_overseed_skip_treats_an_unset_window_as_not_yet_recorded` | `test_engine_intents.py::test_overseed_hold_skips_the_day_once` |
| `test_active_group_wins_over_scheduled_for_wetness` | `engine/test_schedule.py::test_select_group_precedence` |
| `test_scheduled_group_drives_when_no_active_session` | `engine/test_schedule.py::test_select_group_precedence`<br>`test_entities.py::test_optimal_reads_the_selected_groups_wetness` |
| `test_falls_back_to_computed_group_when_nothing_stamped` | `engine/test_schedule.py::test_select_group_precedence` |
| `test_no_group_requires_both_groups_dry` | `engine/test_conditions.py::test_dry_reads_only_the_selected_group`<br>`engine/test_schedule.py::test_select_group_precedence` |

## `test_reprompt.py`

| luba-tests | Port |
|---|---|
| `test_reprompt_interval_helper_exists` | `test_config_flow.py::test_options_timing_types_and_normalises` |
| `test_old_timeout_and_delay_helpers_are_gone` | retired — YAML helpers; the port has one `reprompt_interval_minutes` option<br>`test_config_flow.py::test_options_timing_types_and_normalises` |
| `test_no_reference_to_the_retired_helpers_remains` | retired — YAML helpers |
| `test_reprompt_never_transitions_to_delayed` | `test_engine_invariants.py::test_table_is_exactly_what_the_intents_write` |
| `test_reprompt_holds_and_redispatches_prompt_user_when_conditions_hold` | `test_engine_intents.py::test_snooze_rearms_the_deadline_and_reprompts_later`<br>`test_engine_safety.py::test_stale_prompt_nonce_is_rejected` |
| `test_reprompt_conditions_hold_arm_rearms_deadline_before_dispatching_prompt_user` | `test_engine_intents.py::test_snooze_rearms_the_deadline_and_reprompts_later` |
| `test_reprompt_falls_back_to_scheduled_and_clears_the_push_when_conditions_lapse` | `test_engine_intents.py::test_reprompt_with_conditions_lapsed_returns_to_scheduled` |
| `test_reprompt_ignores_a_fire_from_the_wrong_state` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count` |
| `test_delay_snoozes_without_changing_the_fsm` | `test_engine_intents.py::test_snooze_rearms_the_deadline_and_reprompts_later` |
| `test_start_and_skip_clear_the_prompt` | `test_engine_day.py::test_happy_day_prompt_start_complete_log_count`<br>`test_engine_safety.py::test_skip_then_close_window_logs_skipped` |
| `test_no_intent_branch_references_delayed` | `test_engine_invariants.py::test_table_is_exactly_what_the_intents_write` |
| `test_close_window_clears_the_prompt_on_a_lost_day` | `test_engine_details.py::test_close_window_withdraws_the_prompt_on_a_lost_day` |

## `test_review_m3_m6_l1.py`

| luba-tests | Port |
|---|---|
| `test_every_notify_in_the_package_is_best_effort` | `test_engine_details.py::test_a_failing_notify_never_stops_an_intent` |
| `test_schedule_day_mower_calls_cannot_halt_the_day` | `test_engine_details.py::test_a_raising_dock_cannot_halt_the_stale_sweep` |
| `test_a_failed_cancel_still_escalates_to_error` | `test_engine_intents.py::test_uncancellable_stale_job_is_an_error` |
| `test_irrigation_tracker_ignores_availability_flaps` | retired — the environmental package is not Luba's and is not ported (design Q7) |
| `test_orchestrator_keeps_enough_traces_to_diagnose_a_completion` | retired — no script traces; every transition is one logbook line with a corr token, and each completion payload is logged before its calendar write<br>`test_engine_writer.py::test_every_state_change_has_exactly_one_logbook_line` |

## `test_review_remaining.py`

| luba-tests | Port |
|---|---|
| `test_telemetry_idle_checks_status_before_chaining_log_completion` | retired — a refused write raises before anything is chained (review M2)<br>`test_engine_writer.py::test_illegal_transition_raises_and_becomes_an_error` |
| `test_a_restart_after_the_scheduler_time_redispatches_schedule_day` | `test_engine_restart.py::test_restart_spanning_the_scheduler_time_keeps_the_day` |
| `test_the_missed_trigger_branch_stays_quiet_otherwise` | `test_engine_restart.py::test_restart_spanning_the_scheduler_time_keeps_the_day` |
| `test_an_unset_evaluation_window_counts_as_not_run_today` | `test_engine_restart.py::test_restart_spanning_the_scheduler_time_keeps_the_day` |
| `test_the_missed_trigger_branch_only_dispatches` | `test_engine_restart.py::test_restart_spanning_the_scheduler_time_keeps_the_day` |
| `test_orchestrator_overflow_fails_loud` | `test_engine_details.py::test_queue_overflow_raises_a_repair_issue` |
| `test_session_number_helpers_survive_a_restart` | `test_engine_restart.py::test_restart_mid_session_loses_nothing` |
| `test_the_quiet_error_sweep_sits_between_mowed_today_and_the_plain_sweep` | `test_engine_intents.py::test_error_on_a_non_mow_day_is_swept_silently`<br>`test_engine_details.py::test_error_on_a_mow_day_without_a_mow_is_no_mow_today`<br>`test_replay.py::test_0822_an_error_at_close_after_a_mow_is_swept_silently` |
| `test_the_quiet_error_sweep_writes_no_calendar_entry_or_status_push` | `test_engine_intents.py::test_error_on_a_non_mow_day_is_swept_silently` |
| `test_handled_today_reads_the_evaluation_window` | `test_engine_intents.py::test_error_on_a_non_mow_day_is_swept_silently`<br>`test_engine_details.py::test_error_on_a_mow_day_without_a_mow_is_no_mow_today` |
| `test_optimal_and_schedule_day_pick_the_same_group` | `engine/test_schedule.py::test_group_for_matrix`<br>`engine/test_schedule.py::test_select_group_precedence` |
| `test_the_quiet_error_sweep_fires_only_for_error_on_a_non_mow_day` | `test_engine_intents.py::test_error_on_a_non_mow_day_is_swept_silently`<br>`test_engine_details.py::test_error_on_a_mow_day_without_a_mow_is_no_mow_today` |
