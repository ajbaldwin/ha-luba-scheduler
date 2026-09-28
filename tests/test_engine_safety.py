"""Safety must-haves (design Q9): gate and adverse re-read per attempt, shadow, one commander."""
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from custom_components.luba import const as c
from custom_components.luba.commander import ISSUE_YAML_ACTIVE
from custom_components.luba.engine import fsm as F

from .world import MOWER_SERVICES, build, fire_action, fsm, later, settle, tick


async def _awaiting(hass, freezer, **kw):
    world, entry = await build(hass, freezer, **kw)
    await tick(hass, entry, freezer, later(minutes=5))           # 08:45 → prompt
    assert fsm(entry) == F.AWAITING
    return world, entry


# ---- H1 / M1: every attempt re-reads the gate and the adverse sensor ------------------

async def test_gate_opens_between_attempts_no_second_command(hass, freezer):
    """H1: attempt 1 is ignored, the gate opens meanwhile → attempt 2 is never sent."""
    world, entry = await _awaiting(hass, freezer)
    world.react("mammotion.start_mow", lambda w, _d: w.open_gate())
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert len(world.called("mammotion.start_mow")) == 1
    assert fsm(entry) == F.ERROR
    assert "gate open before start attempt 2" in entry.runtime_data.store.fsm.last_corr or \
        any("gate open before start attempt 2" in n["message"] for n in world.notifications)


async def test_adverse_between_attempts_no_second_command(hass, freezer):
    """M1: attempt 1 is ignored, rain starts meanwhile → attempt 2 is never sent."""
    world, entry = await _awaiting(hass, freezer)
    world.react("mammotion.start_mow", lambda w, _d: w.rain())
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert len(world.called("mammotion.start_mow")) == 1
    assert fsm(entry) == F.ERROR
    assert any("adverse conditions before start attempt 2" in n["message"]
               for n in world.notifications)


async def test_ignored_starts_retry_up_to_the_attempt_limit(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    world.ignore("mammotion.start_mow", times=3)
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert len(world.called("mammotion.start_mow")) == 3
    assert fsm(entry) == F.ERROR


async def test_third_attempt_accepted(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    world.ignore("mammotion.start_mow", times=2)
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert len(world.called("mammotion.start_mow")) == 3
    assert fsm(entry) == F.RUNNING


async def test_gate_open_at_tap_sends_nothing(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    world.open_gate()
    await settle(hass, entry, freezer)
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert world.called("mammotion.start_mow") == []
    assert fsm(entry) == F.AWAITING
    # closing it re-prompts (#11 gate_recover → prompt_user)
    before = len(world.prompts())
    world.open_gate(False)
    await settle(hass, entry, freezer)
    assert len(world.prompts()) == before + 1


async def test_adverse_at_tap_refuses_without_starting(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    world.rain()
    await settle(hass, entry, freezer)
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert world.called("mammotion.start_mow") == []
    assert fsm(entry) == F.AWAITING
    assert any(n.get("title", "").endswith("Not Safe to Start") for n in world.notifications)


# ---- shadow ----------------------------------------------------------------------------

async def test_shadow_never_calls_a_real_service(hass, freezer):
    """A whole shadow day: the YAML (simulated) runs the mower; Luba follows and commands nothing."""
    world, entry = await build(hass, freezer, active=False)
    world.follow_shadow(entry)
    co = entry.runtime_data
    co.async_update_settings(auto_start=True)
    await tick(hass, entry, freezer, later(minutes=5))          # auto-start runs start_mow
    assert fsm(entry) == F.RUNNING
    await tick(hass, entry, freezer, later(minutes=60))
    world.finish()
    await settle(hass, entry, freezer)
    await tick(hass, entry, freezer, later(minutes=3))
    assert fsm(entry) == F.IDLE, (co.dispatcher.handled, world.mode)
    assert co.store.counters.cuts["A"] == 1

    assert world.calls == [] and world.notifications == [] and world.events == []
    assert [name for name, _ in co.commander.calls] == ["mammotion.start_mow"]
    assert any(s["service"] == "calendar.create_event" for s in co.notifier.sent)


async def test_shadow_adopts_a_run_the_yaml_started(hass, freezer):
    """No tap reaches Luba in shadow (the owner taps the YAML's MOW_* prompt)."""
    world, entry = await build(hass, freezer, active=False)
    await tick(hass, entry, freezer, later(minutes=5))
    assert fsm(entry) == F.AWAITING
    hass.bus.async_fire("mobile_app_notification_action", {"action": "MOW_START_NOW"})
    await settle(hass, entry, freezer)
    assert fsm(entry) == F.AWAITING                               # not ours: ignored
    world.start_job_for("Front", "Side")
    world.set_mode(c.MODE_WORKING)
    await settle(hass, entry, freezer)
    assert fsm(entry) == F.RUNNING
    assert entry.runtime_data.store.session.active_group == ""   # adoption fills only a blank group
    assert entry.runtime_data.commander.calls == []
    assert world.calls == []


# ---- exactly one system commands the mower ---------------------------------------------

async def test_active_refused_while_a_yaml_automation_is_on(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    hass.states.async_set("automation.luba_scheduler", "on")
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert world.calls == []
    assert fsm(entry) == F.ERROR
    assert ir.async_get(hass).async_get_issue(c.DOMAIN, ISSUE_YAML_ACTIVE) is not None


async def test_active_refused_on_start_mow_drift(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    hass.services.async_remove(c.MAMMOTION, "start_mow")
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert world.called("mammotion.start_mow") == []
    assert fsm(entry) == F.ERROR


# ---- prompts -----------------------------------------------------------------------------

async def test_stale_prompt_nonce_is_rejected(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    old = world.last_prompt_action(c.ACT_START)
    # the heartbeat re-prompts with a fresh nonce
    await tick(hass, entry, freezer, later(minutes=31))
    new = world.last_prompt_action(c.ACT_START)
    assert new != old
    await fire_action(hass, entry, old, freezer)
    assert world.called("mammotion.start_mow") == []
    assert world.notifications[-1]["message"] == "That prompt has expired."
    assert fsm(entry) == F.AWAITING
    await fire_action(hass, entry, new, freezer)
    assert len(world.called("mammotion.start_mow")) == 1


async def test_foreign_and_nonceless_actions(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    await fire_action(hass, entry, "MOW_START_NOW")                # the YAML's: ignored
    await fire_action(hass, entry, c.ACT_START)                    # no nonce: expired
    assert world.called("mammotion.start_mow") == []
    assert world.notifications[-1]["message"] == "That prompt has expired."


async def test_skip_then_close_window_logs_skipped(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_SKIP), freezer)
    assert fsm(entry) == F.SKIPPED
    assert world.notifications[-1]["message"] == "clear_notification"   # the answered prompt goes
    await tick(hass, entry, freezer, later(hours=4, minutes=20))  # past window close
    assert fsm(entry) == F.IDLE
    assert world.events[-1]["summary"] == "Mowing — Group A, Skipped"


# ---- re-slug and rebuilt zones -------------------------------------------------------------

async def test_reslugged_zone_sends_its_new_entity_id(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    world.reslug("Front", "switch.outside_test_mower_area_front")
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    areas = world.called("mammotion.start_mow")[0]["areas"]
    assert "switch.outside_test_mower_area_front" in areas
    assert fsm(entry) == F.RUNNING                                # route verify used unique_ids


async def test_rebuilt_zone_refuses_a_partial_mow(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    er.async_get(hass).async_remove(world.mower.zones["Side"])
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert world.called("mammotion.start_mow") == []
    assert fsm(entry) == F.ERROR
    assert "resolved only 1/2" in world.notifications[-1]["message"]


async def test_mower_services_are_exactly_the_four(hass, freezer):
    world, _entry = await build(hass, freezer)
    for full in MOWER_SERVICES:
        domain, service = full.split(".")
        assert hass.services.has_service(domain, service)
