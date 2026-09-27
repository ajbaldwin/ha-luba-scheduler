"""One FIFO queue, one worker: the YAML orchestrator's ``mode: queued``, kept.

Two properties the 08:45 race guards depend on (handoff §3) are preserved:

* FIFO order across every source (listeners, chained intents, the UI);
* an intent that chains another ENQUEUES it (``dispatch``) and never awaits it
  inline — ``script.turn_on`` semantics. Awaiting a chained intent from inside
  a handler would deadlock the single worker.

Overflow is loud (review L2): a critical log line and a repair issue, never a
silently dropped intent.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .fsm_writer import TransitionRefused

_LOGGER = logging.getLogger(__name__)
QUEUE_MAX = 50
ISSUE_OVERFLOW = "queue_overflow"


@dataclass(frozen=True)
class Intent:
    name: str
    ctx: dict[str, Any] = field(default_factory=dict)


class Dispatcher:
    def __init__(self, hass: HomeAssistant,
                 handler: Callable[[Intent], Awaitable[None]]) -> None:
        self._hass = hass
        self._handler = handler
        self._queue: asyncio.Queue[Intent] = asyncio.Queue(maxsize=QUEUE_MAX)
        self._task: asyncio.Task | None = None
        self.handled: list[str] = []        # intent names, in order (diagnostics/tests)

    @callback
    def dispatch(self, name: str, **ctx: Any) -> bool:
        try:
            self._queue.put_nowait(Intent(name, ctx))
        except asyncio.QueueFull:
            _LOGGER.critical("Luba intent queue full (%d): dropped %s %s", QUEUE_MAX, name, ctx)
            ir.async_create_issue(self._hass, DOMAIN, ISSUE_OVERFLOW, is_fixable=False,
                                  severity=ir.IssueSeverity.CRITICAL,
                                  translation_key=ISSUE_OVERFLOW,
                                  translation_placeholders={"intent": name})
            return False
        return True

    @callback
    def start(self, create_task: Callable[..., asyncio.Task]) -> None:
        self._task = create_task(self._run(), "luba_dispatcher")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def join(self) -> None:
        """Wait until every queued intent, including chained ones, has run (tests)."""
        await self._queue.join()

    async def _run(self) -> None:
        while True:
            intent = await self._queue.get()
            try:
                self.handled.append(intent.name)
                await self._handler(intent)
            except TransitionRefused as err:
                _LOGGER.error("%s", err)
                if intent.name != "enter_error":
                    self.dispatch("enter_error", error_context=str(err))
            except Exception:  # noqa: BLE001 — one bad intent must not kill the worker
                _LOGGER.exception("Luba intent %s failed", intent.name)
                if intent.name != "enter_error":
                    self.dispatch("enter_error",
                                  error_context=f"{intent.name}: unexpected failure (see log)")
            finally:
                self._queue.task_done()
