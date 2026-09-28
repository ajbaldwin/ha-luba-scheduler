"""The orchestrator: one handler per intent, run one at a time by the dispatcher.

Ported from ``script.luba_orchestrator`` (PRD v3.1.47) with the design's
cleanups:

* no ``Charging`` state (review M5): a docked, held job is ``Paused`` with the
  charging sensor on; ``charge_threshold_reached`` / ``charging_timer_expired``
  and both timers are gone;
* ``_suspended`` is the hardware holding a job (``MODE_PAUSE``/``MODE_PAUSED``);
* every mower call goes through the commander (gate + adverse re-read on every
  attempt), every notify/calendar call through the best-effort notifier;
* notification actions carry a prompt nonce, so a stale tap is told so;
* chained intents are ENQUEUED (``self._dispatch``), never awaited inline.

Handlers read state fresh (``self.fsm.state``); they never trust a value
captured before a wait.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (async_call_later, async_track_state_change_event,
                                         async_track_time_interval)
from homeassistant.util import dt as dt_util

from . import audit
from . import const as c
from .commander import CommandRefused, MowerCommander
from .dispatcher import Intent
from .engine import fsm as F
from .engine.rotation import next_in, seasonal_cuts_per_group, seasonal_height
from .engine.schedule import group_for
from .fsm_writer import FsmWriter
from .mammotion import resolve
from .notifier import TAG_PROMPT, TAG_STATUS, Notifier

_LOGGER = logging.getLogger(__name__)
_BAD = ("", STATE_UNKNOWN, STATE_UNAVAILABLE, "none", "None")


def _today_at(hhmmss: str, now: datetime) -> datetime:
    h, m, s = (int(p) for p in (hhmmss.split(":") + ["0", "0"])[:3])
    return now.replace(hour=h, minute=m, second=s, microsecond=0)


def _date_of(iso: str) -> str:
    return iso[:10] if iso else ""


def _before_todays_close(now: datetime, close: datetime | None) -> bool:
    """Before TODAY's start cutoff. The close is built on sun.sun's next_setting,
    which after sunset is tomorrow's, so `now < close` alone holds all night."""
    return close is not None and now < close and dt_util.as_local(close).date() == now.date()


class Orchestrator:
    def __init__(self, hass: HomeAssistant, coordinator, fsm: FsmWriter,
                 commander: MowerCommander, notifier: Notifier,
                 dispatch: Callable[..., bool]) -> None:
        self.hass, self.co, self.fsm = hass, coordinator, fsm
        self.cmd, self.notify, self._dispatch = commander, notifier, dispatch
        self._handlers = {
            "schedule_day": self.schedule_day, "prompt_user": self.prompt_user,
            "handle_action": self.handle_action, "start_mow": self.start_mow,
            "evaluate_readiness": self.evaluate_readiness,
            "telemetry_sync": self.telemetry_sync, "telemetry_offline": self.telemetry_offline,
            "telemetry_idle": self.telemetry_idle, "reboot_recover": self.reboot_recover,
            "conditions_recovered": self.conditions_recovered, "reprompt": self.reprompt,
            "close_window": self.close_window, "hard_stop": self.hard_stop,
            "gate_recover": self.gate_recover, "adverse_abort": self.adverse_abort,
            "rotate_settings": self.rotate_settings, "log_completion": self.log_completion,
            "log_cut": self.log_cut, "count_group_cut": self.count_group_cut,
            "enter_error": self.enter_error, "clear_error": self.clear_error,
        }

    INTENTS = ("schedule_day", "prompt_user", "handle_action", "start_mow",
               "evaluate_readiness", "telemetry_sync", "telemetry_offline", "telemetry_idle",
               "reboot_recover", "conditions_recovered", "reprompt", "close_window", "hard_stop",
               "gate_recover", "adverse_abort", "rotate_settings", "log_completion", "log_cut",
               "count_group_cut", "enter_error", "clear_error")

    async def handle(self, intent: Intent) -> None:
        handler = self._handlers.get(intent.name)
        if handler is None:
            _LOGGER.warning("unknown Luba intent %r", intent.name)
            return
        await handler(**intent.ctx)

    # ==== state reads =============================================================

    @property
    def opts(self) -> dict[str, Any]:
        return self.co.opts

    @property
    def store(self):
        return self.co.store

    def _role(self, role: str) -> str | None:
        return resolve(self.hass, self.opts.get(c.CONF_ROLES, {}).get(role))

    def _state(self, entity_id: str | None) -> str | None:
        st = self.hass.states.get(entity_id) if entity_id else None
        return None if st is None or st.state in _BAD else st.state

    def mode(self) -> str | None:
        return self._state(self._role(c.ROLE_ACTIVITY))

    def battery(self) -> float | None:
        try:
            value = self._state(self._role(c.ROLE_BATTERY))
            return float(value) if value is not None else None
        except ValueError:
            return None

    def charging(self) -> bool:
        return self._state(self._role(c.ROLE_CHARGING)) == "on"

    def suspended(self) -> bool:
        """The hardware holds an unfinished job (docked or on the lawn)."""
        return self.mode() in (c.MODE_PAUSE, c.MODE_PAUSED)

    def on_lawn(self) -> bool:
        """MODE_PAUSE is not "on the lawn": a docked held job reports it too (defect 13)."""
        return self.mode() in (c.MODE_WORKING, c.MODE_PAUSE, c.MODE_PAUSED) and not self.charging()

    def _group_switch_uids(self) -> dict[str, set[str]]:
        reg = er.async_get(self.hass)
        out: dict[str, set[str]] = {}
        for group, bindings in self.opts.get(c.CONF_ZONES, {}).items():
            entries = [reg.async_get(b[c.BIND_ID]) for b in bindings]
            out[group] = {e.unique_id for e in entries if e is not None}
        return out

    def live_zone_uids(self) -> set[str]:
        """Switch unique_ids whose task-area sensor exists now with a real state."""
        device = self.opts.get(c.CONF_DEVICE)
        if not device:
            return set()
        live = set()
        for entry in er.async_entries_for_device(er.async_get(self.hass), device):
            if (entry.domain == "sensor" and entry.platform == c.MAMMOTION
                    and entry.unique_id.endswith(c.TASK_AREA_SUFFIX)
                    and self._state(entry.entity_id) is not None):
                live.add(entry.unique_id.removesuffix(c.TASK_AREA_SUFFIX))
        return live

    def held_group(self) -> str:
        """The group whose zones EXACTLY match the live job's task areas, else ''."""
        live = self.live_zone_uids()
        for group, uids in self._group_switch_uids().items():
            if uids and live == uids:
                return group
        return ""

    def snap(self):
        return self.co.recompute()

    def adverse_reason(self) -> str:
        terms, r, t = self.snap().adverse_terms, self.co.readings(), self.co.thresholds()
        if terms["precipitation"]:
            return f"Weather: {r.precip_type}"
        if terms["severe_weather"]:
            return f"Weather: {r.weather}"
        if terms["lightning"]:
            return f"Lightning within {t.lightning_radius:g}"
        if terms["heat"]:
            return f"Canopy heat > {t.canopy_max_f:g}°F"
        if terms["darkness"]:
            return "Darkness"
        return "Adverse conditions"

    def _abort_set(self) -> bool:
        return bool(self.store.session.abort_reason)

    def _minutes(self, key: str) -> timedelta:
        return timedelta(minutes=self.opts[key])

    @property
    def mower(self) -> str:
        return self.co.mower_name

    def _now(self) -> datetime:
        return dt_util.now()

    def _log(self, message: str) -> None:
        audit.log(self.hass, message)

    def _save(self) -> None:
        self.store.async_delay_save()
        self.co.recompute()

    async def _wait_for(self, predicate: Callable[[], bool], timeout: float,
                        watch: list[str] | None = None) -> bool:
        """True as soon as predicate holds (checked on each watched change and every second).

        The deadline and the poll are Home Assistant timers, not the event loop's
        clock, so they follow HA time (and tests can advance it).
        """
        if predicate():
            return True
        done = asyncio.Event()

        @callback
        def _check(*_: Any) -> None:
            if predicate():
                done.set()

        @callback
        def _expire(_now: datetime) -> None:
            done.set()

        unsubs = [async_call_later(self.hass, timeout, _expire),
                  async_track_time_interval(self.hass, _check, timedelta(seconds=1))]
        if watch:
            unsubs.append(async_track_state_change_event(self.hass, watch, _check))
        try:
            await done.wait()
            return predicate()
        finally:
            for unsub in unsubs:
                unsub()

    def _new_prompt_id(self) -> str:
        self.store.day.prompt_id = secrets.token_hex(4)
        self._save()
        return self.store.day.prompt_id

    def _arm_ack_deadline(self) -> None:
        self.store.day.ack_deadline = (self._now() + self._minutes(c.CONF_REPROMPT)).isoformat()
        self._save()
        self.co.async_arm_deadlines()

    def _reconcile_active_group(self) -> None:
        """At every exit to Idle / Skipped Today / Error (review H2)."""
        self.store.session.active_group = self.held_group() if self.suspended() else ""
        self._save()

    def _reset_session(self) -> None:
        s = self.store.session
        s.start, s.battery_start, s.work_area = "", None, ""
        s.active_group, s.recharge_count, s.abort_reason = "", 0, ""
        self._save()

    def _error(self, context: str) -> None:
        self._dispatch("enter_error", error_context=context)

    # ==== scheduling ===============================================================

    async def schedule_day(self) -> None:
        r = self.co.readings()
        if r.season_on is not True:
            return
        now = self._now()
        freq = self.store.settings.cuts_per_group
        group = group_for(now.weekday(), freq)
        if group not in ("A", "B"):
            return
        today = now.date().isoformat()

        # Overseed hold (§5.19; lawn_growth mowing_allowed is the authority, design Q7).
        if self.snap().overseed_hold.get(group):
            if _date_of(self.store.day.evaluated_at) != today:
                await self.notify.calendar(
                    f"Mowing — Group {group}, Skipped (overseed)",
                    f"No mow today. Group {group} is on overseed hold while the new grass establishes.",
                    now, now + timedelta(minutes=1))
                self.store.day.evaluated_at = now.isoformat()
                self._save()
                self._log(f"schedule_day: Group {group} on overseed hold — no mow today")
                await self.notify.notify(f"{self.mower} — No Mow Today",
                                         f"Group {group} is on overseed hold; the new grass is "
                                         "establishing, so no mow today.")
            return

        fsm_now = self.fsm.state
        ref = self.store.session.start or self.store.day.evaluated_at
        is_today = fsm_now != F.IDLE and _date_of(ref) == today
        if is_today:
            return
        suspended = self.suspended()
        if suspended and fsm_now in (F.AWAITING, F.STARTING, F.RUNNING):
            return                                   # recovery already in flight
        if fsm_now != F.IDLE and not suspended:       # stale carry-over from a past day
            if self.mode() in (c.MODE_WORKING, c.MODE_PAUSE, c.MODE_PAUSED, c.MODE_RETURNING):
                try:
                    await self.cmd.dock()
                except (CommandRefused, Exception) as err:  # noqa: BLE001 — review M3
                    self._log(f"schedule_day: stale-sweep dock failed: {err}")
                await self._wait_for(lambda: self.mode() in (c.MODE_IDLE, c.MODE_READY,
                                                             c.MODE_CHARGING, c.MODE_FINISHED),
                                     c.STALE_DOCK_WAIT_S, [self._role(c.ROLE_ACTIVITY)])
            self._log(f"schedule_day: stale carry-over '{fsm_now}' cleared")
            self._reset_session()
            await self.fsm.transition(F.IDLE, "schedule_day", "scheduler",
                                      f"stale carry-over: {fsm_now}")
            await self.notify.notify(f"{self.mower} — Session Cleaned Up",
                                     f"Cleaned up yesterday's unfinished session: {fsm_now}")
        if self.mode() == c.MODE_WORKING:
            try:
                await self.cmd.cancel_job()
            except (CommandRefused, Exception) as err:  # noqa: BLE001
                self._log(f"schedule_day: cancel_job failed: {err}")
            if not await self._wait_for(
                    lambda: self.mode() not in (c.MODE_PAUSE, c.MODE_PAUSED, c.MODE_WORKING),
                    self.opts[c.CONF_CANCEL_TIMEOUT], [self._role(c.ROLE_ACTIVITY)]):
                self._error("schedule_day: could not cancel the stale job within the cancel "
                            "timeout; mowing aborted.")
                return
        self.store.day.evaluated_at = now.isoformat()
        self.store.day.scheduled_group = group
        self._save()
        await self.fsm.transition(F.SCHEDULED, "schedule_day", "scheduler")
        self._dispatch("prompt_user")

    async def prompt_user(self) -> None:
        if self.fsm.state not in (F.SCHEDULED, F.AWAITING):
            return                                    # stale dispatch
        snap = self.snap()
        if not (snap.optimal and snap.ready):
            await self.notify.notify(f"{self.mower} — Waiting",
                                     f"Mow day: waiting for conditions. Optimal: {snap.optimal}, "
                                     f"Ready: {snap.ready}.")
            return
        await self.fsm.transition(F.AWAITING, "prompt_user", "scheduler")
        self._arm_ack_deadline()
        if snap.adverse:
            await self.notify.notify(f"{self.mower} — Waiting",
                                     f"Ready to mow, but not safe right now: {self.adverse_reason()}. "
                                     "I'll prompt again when it clears.", TAG_PROMPT)
            return
        if not self.cmd.gate_closed():
            await self.notify.notify(f"{self.mower} — Gate Open",
                                     "Ready to mow, but the gate is open. Please close it.",
                                     TAG_PROMPT)
            return
        if self.store.settings.auto_start:
            self._dispatch("start_mow")
            return
        pid = self._new_prompt_id()
        await self.notify.notify(
            f"{self.mower} — Ready to Mow",
            f"Ready to mow. Start now, delay {self.opts[c.CONF_REPROMPT]} min, or skip?",
            TAG_PROMPT,
            [{"action": f"{c.ACT_START}:{pid}", "title": "Start Now"},
             {"action": f"{c.ACT_SNOOZE}:{pid}",
              "title": f"Delay {self.opts[c.CONF_REPROMPT]} min"},
             {"action": f"{c.ACT_SKIP}:{pid}", "title": "Skip Today"}])

    async def handle_action(self, action: str = "") -> None:
        name, _, nonce = action.partition(":")
        fsm_now = self.fsm.state
        if name == c.ACT_TOGGLE_AUTO:
            self.co.async_update_settings(auto_start=not self.store.settings.auto_start)
            await self.notify.notify(f"{self.mower} — Auto-Start",
                                     f"Auto-start is now {'on' if self.store.settings.auto_start else 'off'}.")
            return
        if name == c.ACT_CLEAR_ERROR:
            if fsm_now == F.ERROR:
                self._dispatch("clear_error")
            else:
                self._log(f"Stale action ignored: {name} while FSM is {fsm_now}")
            return
        if nonce != self.store.day.prompt_id or not nonce:
            self._log(f"Expired prompt tapped: {action} (current prompt {self.store.day.prompt_id or 'none'})")
            await self.notify.notify(f"{self.mower}", "That prompt has expired.")
            return
        if name == c.ACT_START and fsm_now == F.AWAITING:
            await self.notify.clear()
            self._dispatch("start_mow")
        elif name == c.ACT_SNOOZE and fsm_now == F.AWAITING:
            self._arm_ack_deadline()
        elif name == c.ACT_SKIP and fsm_now in (F.AWAITING, F.PAUSED):
            await self.fsm.transition(F.SKIPPED, "handle_action", "user_action")
            self._reconcile_active_group()
            await self.notify.clear()
        elif name == c.ACT_RESUME and fsm_now == F.AWAITING:
            self._dispatch("start_mow")
        else:
            self._log(f"Stale action ignored: {name} requested while FSM is {fsm_now}")

    async def start_mow(self) -> None:
        is_resume = self.suspended()
        floor = self.opts[c.CONF_RESUME_FLOOR] if is_resume else self.opts[c.CONF_START_FLOOR]
        battery = self.battery()
        stamped = self.store.day.scheduled_group
        held = self.held_group()
        grp = stamped if stamped in ("A", "B") else held
        fsm_now = self.fsm.state

        if not self.cmd.gate_closed():
            await self.notify.notify(f"{self.mower} — Gate Open",
                                     "Start blocked: the gate is open. Close it to proceed.", TAG_PROMPT)
            return
        if self.snap().adverse:
            reason = self.adverse_reason()
            await self.notify.notify(f"{self.mower} — Not Safe to Start",
                                     f"Not safe to start: {reason}. I'll prompt again when it clears.",
                                     TAG_PROMPT)
            self._log(f"start_mow: refused under adverse conditions ({reason}), FSM {fsm_now}")
            return
        if self.mode() == c.MODE_WORKING and fsm_now in (F.STARTING, F.RUNNING):
            self._log(f"start_mow: mower already working in {fsm_now} — duplicate dispatch ignored")
            return
        if fsm_now != F.AWAITING:
            self._log(f"start_mow: FSM is {fsm_now}, not awaiting a start — ignored")
            return
        if not is_resume and grp not in ("A", "B"):
            self._error("start_mow: no zone group stamped — refusing a fresh start rather than "
                        "guessing which half of the lawn to mow.")
            return
        if is_resume and held and held != grp:
            await self.notify.notify(f"{self.mower} — Group {held} carried over",
                                     f"Resuming group {held}'s unfinished job instead of starting "
                                     f"group {grp}. Group {grp} is skipped this week.")
        if battery is None or battery < floor or self.mode() == c.MODE_WORKING:
            self._error(f"start_mow: pre-start check failed (battery {battery}% vs floor {floor}%, "
                        f"mode {self.mode()}, FSM {fsm_now})")
            return
        await self.fsm.transition(F.STARTING, "start_mow", "user_action")

        areas: list[str] = []
        if not is_resume:
            bindings = self.opts.get(c.CONF_ZONES, {}).get(grp, [])
            for b in bindings:
                entity_id = resolve(self.hass, b[c.BIND_ID])
                st = self.hass.states.get(entity_id) if entity_id else None
                if st is not None and st.attributes.get("hash") is not None:
                    areas.append(entity_id)
            if len(areas) != len(bindings) or not bindings:
                self._error(f"start_mow: resolved only {len(areas)}/{len(bindings)} area hashes — "
                            "a zone switch is missing or unavailable. Refusing a partial mow.")
                return
            if self.co.data.angle.out_of_range:
                self._log(f"start_mow: group {grp} is already beyond the schedule this week — "
                          f"{self.co.data.angle.plan}")

        activity = self._role(c.ROLE_ACTIVITY)
        attempts = self.opts[c.CONF_START_ATTEMPTS]
        for attempt in range(1, attempts + 1):
            try:
                if is_resume:
                    await self.cmd.resume()
                else:
                    angle = self.co.data.angle
                    await self.cmd.start(areas, blade_height=self.store.settings.cutting_height,
                                         channel_width=self.co.spacing, toward=angle.toward,
                                         toward_mode=angle.toward_mode)
            except CommandRefused as err:
                self._error(f"start_mow: {err.reason} before start attempt {attempt} — no command "
                            "sent. Resolve it, clear the error, and start again.")
                return
            except Exception as err:  # noqa: BLE001 — a raised call is retried like a no-op
                self._log(f"start_mow: attempt {attempt} raised {err}")
            if await self._wait_for(lambda: self.mode() == c.MODE_WORKING,
                                    self.opts[c.CONF_START_VERIFY], [activity]):
                break
        if self.mode() != c.MODE_WORKING:
            hint = (" The pending job may be unresumable — cancel it in the Mammotion app, or "
                    "every start will retry it." if is_resume else "")
            self._error(f"Start command issued {attempts}x ({'resume' if is_resume else 'fresh start'}) "
                        f"but the mower did not begin working within "
                        f"{self.opts[c.CONF_START_VERIFY]}s per attempt.{hint}")
            return
        if not is_resume:
            want = self._group_switch_uids().get(grp, set())
            if not await self._wait_for(lambda: bool(want) and want <= self.live_zone_uids(),
                                        self.opts[c.CONF_ROUTE_VERIFY]):
                self._error(f"Mower reports working but no route was planned for group {grp} — its "
                            "task areas never appeared, so the job is running on a stale breakpoint "
                            "and every parameter sent was discarded (defect 23). Let it finish or "
                            "cancel it in the Mammotion app, then start again.")
                return
        self.store.session.active_group = held if (is_resume and held in ("A", "B")) else grp
        self._save()

    async def evaluate_readiness(self) -> None:
        """Wake a sleeping docked mower whose camera still reads last night (v3.1.40)."""
        r = self.co.readings()
        if r.sun_above is True and r.camera != "Light":
            ids = [e for e in (self._role(c.ROLE_CAMERA), self._role(c.ROLE_RTK_FIX),
                               self._role(c.ROLE_ACTIVITY)) if e]
            if not self.cmd.shadow and ids:
                try:
                    await self.hass.services.async_call("homeassistant", "update_entity",
                                                        {"entity_id": ids}, blocking=True)
                except Exception as err:  # noqa: BLE001 — a failed refresh never blocks readiness
                    _LOGGER.debug("readiness refresh failed: %s", err)
                camera = self._role(c.ROLE_CAMERA)
                await self._wait_for(lambda: self._state(camera) == "Light",
                                     c.READINESS_REFRESH_WAIT_S, [camera] if camera else None)
        self.co.recompute()

    # ==== telemetry ==================================================================

    async def telemetry_sync(self, mode_value: str | None = None) -> None:
        mode = mode_value or self.mode()
        fsm_now = self.fsm.state
        target = {c.MODE_WORKING: F.RUNNING, c.MODE_PAUSE: F.PAUSED, c.MODE_PAUSED: F.PAUSED,
                  c.MODE_RETURNING: F.RETURNING}.get(mode or "")
        if mode == c.MODE_CHARGING:
            _LOGGER.warning("Luba: MODE_CHARGING observed (review M5 assumed it never occurs) — "
                            "FSM %s left unchanged; please report", fsm_now)
            self._log(f"telemetry_sync: MODE_CHARGING observed from {fsm_now} — no transition (M5)")
            return
        if fsm_now == F.OFFLINE and mode in (c.MODE_IDLE, c.MODE_READY):
            await self.fsm.transition(F.IDLE, "telemetry_sync", "telemetry",
                                      "offline exit, mower idle at dock")
            self._reconcile_active_group()
            return
        if target is None or target == fsm_now:
            if target is None:
                self._log(f"telemetry_sync: unmapped {mode} from {fsm_now} — no transition")
            return
        if target == F.RUNNING:
            healed = fsm_now == F.ERROR
            if healed and self.store.fsm.error_from != F.STARTING:
                self._log(f"telemetry_sync: working while Error (from {self.store.fsm.error_from}) "
                          "— not healing")
                return
            if not F.is_legal(fsm_now, F.RUNNING):
                self._log(f"telemetry_sync: unmapped {mode} from {fsm_now} — no transition")
                return
            held = self.held_group()
            if held in ("A", "B") and self.store.day.scheduled_group not in ("A", "B"):
                self.store.day.scheduled_group = held
                self.store.session.active_group = held
                self._log(f"telemetry_sync: adopted a run covering group {held} — stamping it")
            if fsm_now in (F.STARTING, F.ERROR):
                s = self.store.session
                s.start = self._now().isoformat()
                s.battery_start = self.battery() or 0
                s.work_area = self._state(self._role(c.ROLE_WORK_AREA)) or ""
                s.abort_reason = ""
                self.store.fsm.error_from = ""
            if healed:
                self._log("telemetry_sync: mower working while FSM was Error after a start from "
                          "Starting — healing to Running")
                sched = self.store.day.scheduled_group
                self.store.session.active_group = held if held in ("A", "B") else (
                    sched if sched in ("A", "B") else "")
            self._save()
            await self.fsm.transition(F.RUNNING, "telemetry_sync", "telemetry")
            return
        if not F.is_legal(fsm_now, target):
            self._log(f"telemetry_sync: unmapped {mode} from {fsm_now} — no transition")
            return
        await self.fsm.transition(target, "telemetry_sync", "telemetry")

    async def telemetry_offline(self) -> None:
        fsm_now = self.fsm.state
        if fsm_now in (F.IDLE, F.OFFLINE):
            return
        self.store.fsm.prior_state = fsm_now
        self._save()
        await self.fsm.transition(F.OFFLINE, "telemetry_offline", "telemetry", f"prior: {fsm_now}")
        await self.notify.notify(f"{self.mower} — Offline",
                                 f"Telemetry lost while {fsm_now}. Mower may be on the lawn — "
                                 "check the Mammotion app.")

    async def telemetry_idle(self) -> None:
        fsm_now = self.fsm.state
        if self.mode() == c.MODE_READY and fsm_now in (F.RUNNING, F.RETURNING) and not self.suspended():
            await self.fsm.transition(F.COMPLETED, "telemetry_idle", "telemetry")
            self._dispatch("log_completion")
        else:
            self._log(f"telemetry_idle: no reconcile — FSM {fsm_now}, mode {self.mode()}, "
                      f"suspended={self.suspended()}")

    async def reboot_recover(self) -> None:
        fsm_now = self.fsm.state
        if fsm_now in F.SESSION_STATES:
            mower, activity = self._role(c.ROLE_MOWER), self._role(c.ROLE_ACTIVITY)
            ok = await self._wait_for(
                lambda: self._state(mower) is not None and self.hass.states.get(activity) is not None
                and self.hass.states.get(activity).state != STATE_UNAVAILABLE,
                c.REBOOT_DEPENDENCY_WAIT_S, [e for e in (mower, activity) if e])
            if not ok:
                self._error(f"Reboot recovery: dependencies not ready: mower={self._state(mower)}, "
                            f"activity={self.mode()}")
                return
            if self.mode() == c.MODE_READY:
                self._dispatch("telemetry_idle")
            else:
                self._dispatch("telemetry_sync", mode_value=self.mode())
        elif fsm_now == F.STARTING:
            self._error("Reboot recovery: FSM was Starting across a restart — start presumed lost.")
        elif fsm_now == F.AWAITING:
            self._arm_ack_deadline()
        elif fsm_now == F.SCHEDULED:
            self._dispatch("prompt_user")
        elif fsm_now == F.IDLE and self._missed_todays_schedule():
            self._log("reboot_recover: restarted after the scheduler time with no schedule_day run "
                      "today — dispatching it now")
            self._dispatch("schedule_day")
        else:
            self._log(f"reboot_recover: FSM {fsm_now} needs no reconciliation")

    def _missed_todays_schedule(self) -> bool:
        """Review M4: a restart spanning the scheduler time must not lose the day."""
        now = self._now()
        close = self.co.data.window_close if self.co.data else None
        return (self.co.readings().season_on is True
                and now >= _today_at(self.opts[c.CONF_SCHEDULER_TIME], now)
                and _before_todays_close(now, close)
                and _date_of(self.store.day.evaluated_at) != now.date().isoformat())

    # ==== conditions, prompts, window ===============================================

    async def conditions_recovered(self, trigger_source: str = "edge") -> None:
        now = self._now()
        if (self.co.readings().season_on is not True
                or now < _today_at(self.opts[c.CONF_SCHEDULER_TIME], now)):
            return
        fsm_now = self.fsm.state
        if fsm_now == F.SCHEDULED and trigger_source != "floor":
            self._dispatch("prompt_user")
            return
        if not (self.suspended() and fsm_now in (F.PAUSED, F.IDLE)):
            return
        snap = self.snap()
        battery = self.battery()
        in_window = _before_todays_close(now, snap.window_close)
        battery_ok = battery is not None and battery >= self.opts[c.CONF_RESUME_FLOOR]
        if not (in_window and battery_ok and self.cmd.gate_closed()):
            return
        if not snap.optimal:
            await self.notify.notify(f"{self.mower} — Job held",
                                     "An unfinished job is waiting for conditions. It will resume "
                                     "automatically when mowing conditions turn optimal.")
            self._log("conditions_recovered: suspended job held, waiting for conditions")
            return
        await self.fsm.transition(F.AWAITING, "conditions_recovered", "recovery",
                                  f"recovery from {fsm_now}")
        self._arm_ack_deadline()
        if self.store.settings.auto_start and snap.optimal and snap.ready and not snap.adverse:
            self._dispatch("start_mow")
            return
        if snap.adverse:
            await self.notify.notify(f"{self.mower} — Waiting",
                                     f"The unfinished job can resume, but not safely right now: "
                                     f"{self.adverse_reason()}. I'll prompt again when it clears.",
                                     TAG_PROMPT)
            return
        pid = self._new_prompt_id()
        reason = self.store.session.abort_reason
        message = (f"Weather abort ({reason}) is over — restart the interrupted session?" if reason
                   else "Conditions look good again — resume the paused session?")
        await self.notify.notify(f"{self.mower} — Conditions Recovered", message, TAG_PROMPT,
                                 [{"action": f"{c.ACT_RESUME}:{pid}", "title": "Resume"},
                                  {"action": f"{c.ACT_SKIP}:{pid}", "title": "Skip Today"}])

    async def reprompt(self) -> None:
        fsm_now = self.fsm.state
        if fsm_now != F.AWAITING:
            self._log(f"reprompt fired while FSM is {fsm_now} — ignored")
            return
        snap = self.snap()
        if snap.optimal and snap.ready:
            self._arm_ack_deadline()
            self._dispatch("prompt_user")
            return
        await self.fsm.transition(F.SCHEDULED, "reprompt", "timeout",
                                  "conditions lapsed while awaiting acknowledgment")
        await self.notify.clear()
        await self.notify.notify(f"{self.mower} — Waiting",
                                 "Conditions paused the mow. I'll prompt again when they clear.")

    async def close_window(self) -> None:
        fsm_now = self.fsm.state
        now = self._now()
        today = now.date().isoformat()
        group = self.store.day.scheduled_group
        prefix = f"Mowing — Group {group}," if group in ("A", "B") else "Mowing —"
        c_ = self.store.counters
        mowed_today = (c_.last_logged_cut.split("|")[-1].strip() == today
                       or c_.last_counted_cut.split("|")[-1].strip() == today)
        handled_today = _date_of(self.store.day.evaluated_at) == today
        one_minute = now + timedelta(minutes=1)

        if fsm_now in (F.IDLE, F.RETURNING, F.COMPLETED):
            return
        if fsm_now == F.PAUSED and self.charging() and self._abort_set():
            # The weather-aborted, docked, held job the YAML parked in Charging (M5).
            reason = self.store.session.abort_reason
            await self.notify.calendar(f"{prefix} Skipped ({reason})",
                                       "Weather-aborted session, never restarted. "
                                       f"Started: {self.store.session.start or 'unknown'}.",
                                       now, one_minute)
            self.store.session.abort_reason = ""
            self._save()
            await self.fsm.transition(F.IDLE, "close_window", "closer",
                                      f"aborted session finalized: {reason}")
        elif fsm_now in (F.PAUSED, F.RUNNING):
            self._log(f"close_window: {fsm_now} past the start cutoff — letting it run to sunset")
            return
        elif fsm_now == F.SKIPPED:
            await self.notify.calendar(f"{prefix} Skipped", "Skipped by the owner.", now, one_minute)
            await self.fsm.transition(F.IDLE, "close_window", "closer")
        elif fsm_now == F.OFFLINE:
            if self.store.fsm.prior_state in (F.RUNNING, F.PAUSED):
                await self.notify.notify(f"{self.mower} — Offline at Day End",
                                         f"{self.mower} is offline and may be on the lawn. Check the "
                                         "Mammotion app.")
            return
        elif self.on_lawn() or self.mode() == c.MODE_RETURNING:
            self._log(f"close_window: {fsm_now} at the cutoff but the mower is {self.mode()} — a "
                      "live run the FSM never adopted; leaving it to telemetry/hard_stop")
            return
        elif fsm_now in (F.SCHEDULED, F.AWAITING, F.ERROR) and mowed_today:
            self._log(f"close_window: {fsm_now} at the cutoff but a mow completed today — sweeping "
                      "to Idle without declaring no-mow")
            await self.notify.clear()
            await self.fsm.transition(F.IDLE, "close_window", "closer",
                                      f"mow completed today; stranded {fsm_now} swept")
        elif fsm_now == F.ERROR and not handled_today:
            self._log("close_window: Error at the cutoff on a non-mow day — sweeping to Idle "
                      "without a no-mow entry")
            await self.notify.clear()
            await self.fsm.transition(F.IDLE, "close_window", "closer", "Error swept on a non-mow day")
        elif fsm_now in (F.SCHEDULED, F.AWAITING, F.ERROR):
            await self.notify.calendar(f"{prefix} Skipped", f"No mow today. State at close: {fsm_now}.",
                                       now, one_minute)
            await self.fsm.transition(F.IDLE, "close_window", "closer", f"window closed from {fsm_now}")
            await self.notify.clear()
            await self.notify.notify(f"{self.mower} — No Mow Today",
                                     f"{self.mower} did not run today. State at close: {fsm_now}.")
        else:
            return
        self._reconcile_active_group()

    async def hard_stop(self) -> None:
        if not self.on_lawn():
            return
        self._log(f"hard_stop: mower still on the lawn at dusk in {self.mode()} — the sunset abort "
                  "did not take")
        if self.fsm.state in (F.STARTING, F.RUNNING, F.PAUSED) and not self._abort_set():
            self.store.session.abort_reason = "Dusk hard stop"
            self._save()
        try:
            await self.cmd.dock()
        except (CommandRefused, Exception) as err:  # noqa: BLE001
            self._log(f"hard_stop: dock call failed: {err}")
        if not await self._wait_for(
                lambda: self.mode() in (c.MODE_RETURNING, c.MODE_CHARGING, c.MODE_IDLE, c.MODE_READY),
                c.DOCK_VERIFY_S, [self._role(c.ROLE_ACTIVITY)]):
            self._error(f"Dusk hard stop failed: mower still on the lawn and did not leave "
                        f"{self.mode()} within 3 min. It may be stranded outside overnight.")
            return
        await self.notify.notify(f"{self.mower} — Hard Stop at Dusk",
                                 f"{self.mower} was still mowing at dusk and has been docked. The sunset "
                                 "abort did not take — worth a look.")

    async def gate_recover(self) -> None:
        if self.fsm.state == F.AWAITING:
            self._dispatch("prompt_user")

    async def adverse_abort(self) -> None:
        if not self.snap().adverse or not self.on_lawn():
            return
        reason = self.adverse_reason()
        in_session = self.fsm.state in (F.STARTING, F.RUNNING, F.PAUSED)
        if in_session:
            self.store.session.abort_reason = reason
            self._save()
        try:
            await self.cmd.dock()
        except (CommandRefused, Exception) as err:  # noqa: BLE001
            self._log(f"adverse_abort: dock call failed: {err}")
        await self.notify.notify("Mowing Aborted!",
                                 f"{reason} — docking {self.mower}."
                                 + ("" if in_session else " (Manual session — no FSM bookkeeping.)"))

    async def rotate_settings(self) -> None:
        settings = self.store.settings
        angles, spacings = self.co.angle_options, self.co.spacing_options
        # Advance from the value the owner sees. Unset (None) shows as the first
        # entry; a stored value the option list no longer holds shows as the first
        # entry too, which is worth a line (the YAML's GAP-6 drift log).
        drifted = [f"{name}={value}" for name, value, seq in
                   (("a1", settings.angle_1, angles), ("sp", settings.spacing, spacings))
                   if value is not None and value not in seq]
        if drifted:
            self._log(f"rotate_settings: unknown current value ({', '.join(drifted)}) — "
                      "rotating from the sequence start")
        today = self._now().date()
        c_ = self.store.counters
        c_.cuts = {"A": 0, "B": 0}
        c_.week_of = today.isoformat()
        self.co.async_update_settings(
            angle_1=next_in(angles, self.co.angle_1),
            spacing=next_in(spacings, self.co.spacing),
            cutting_height=seasonal_height(today),
            cuts_per_group=seasonal_cuts_per_group(today))

    # ==== completion ===================================================================

    async def log_completion(self) -> None:
        self._reset_session()
        await self.fsm.transition(F.IDLE, "log_completion", "system")

    async def log_cut(self) -> None:
        now = self._now()
        s = self.store.session
        has_metrics = _date_of(s.start) == now.date().isoformat()
        held = self.held_group()
        work_area = s.work_area.strip()
        if held in ("A", "B"):
            area = f"Group {held}"
        elif work_area not in ("", "Not working", "path"):
            area = work_area
        else:
            area = "Manual/unknown"
        battery_now = self.battery()
        if has_metrics:
            start = datetime.fromisoformat(s.start)
            mins = round((now - start).total_seconds() / 60)
            summary = f"Mowing — {'Manual' if area == 'Manual/unknown' else area}, {mins} min"
            desc = (f"Start: {start:%Y-%m-%d %H:%M:%S} | End: {now:%Y-%m-%d %H:%M:%S} | "
                    f"Duration: {mins} min | Area: {area} | Battery: {s.battery_start}% -> "
                    f"{battery_now}% | Recharges: {s.recharge_count}")
        else:
            start = now
            summary = f"Mowing — {'Manual' if area == 'Manual/unknown' else area}"
            desc = (f"Adopted from telemetry; no orchestrated session metrics. Area: {area} | "
                    f"End: {now:%Y-%m-%d %H:%M:%S} | Battery now: {battery_now}%")
        key = f"{area}|{now.date().isoformat()}"
        if key != self.store.counters.last_logged_cut:
            _LOGGER.info("luba completion: %s | %s", summary, desc)
            await self.notify.calendar(summary, desc, start, now)
            await self.notify.notify(f"{self.mower} — Mowing Complete", desc)
            self.store.counters.last_logged_cut = key
            self._save()
        self._dispatch("count_group_cut")

    async def count_group_cut(self) -> None:
        grp = self.held_group()
        if grp not in ("A", "B"):
            self._log("count_group_cut: live zones match no group (manual/mixed job or none) — "
                      "not counting")
            return
        key = f"{grp}|{self._now().date().isoformat()}"
        counters = self.store.counters
        if key == counters.last_counted_cut:
            return
        counters.cuts[grp] = counters.cuts.get(grp, 0) + 1
        counters.last_counted_cut = key
        self._save()
        self._log(f"count_group_cut: group {grp} cut {counters.cuts[grp]} of this week recorded")

    # ==== errors ========================================================================

    async def enter_error(self, error_context: str = "no context provided") -> None:
        fsm_now = self.fsm.state
        if fsm_now == F.ERROR:
            _LOGGER.warning("luba: nested error suppressed (FSM already Error): %s", error_context)
            return
        self.store.fsm.error_from = fsm_now
        self._save()
        await self.fsm.transition(F.ERROR, "enter_error", "system", error_context)
        self._reconcile_active_group()
        await self.notify.notify(f"{self.mower} — Error", error_context, TAG_STATUS,
                                 [{"action": c.ACT_CLEAR_ERROR, "title": "Clear Error"}])

    async def clear_error(self) -> None:
        fsm_now = self.fsm.state
        if fsm_now != F.ERROR:
            self._log(f"clear_error ignored: FSM is {fsm_now}")
            return
        await self.fsm.transition(F.IDLE, "clear_error", "user_action")
        self.store.session.abort_reason = ""
        self.store.fsm.error_from = ""
        self._reconcile_active_group()
        await self.notify.notify(f"{self.mower} — Error Cleared", "FSM reset to Idle.")
