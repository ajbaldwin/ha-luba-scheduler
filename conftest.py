import sys
from pathlib import Path

import pytest
from homeassistant.core import EventBus, HassJob, HassJobType

sys.path.insert(0, str(Path(__file__).parent))

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let hass discover custom_components/luba in tests."""
    yield


@pytest.fixture(autouse=True)
def test_listeners_run_in_the_loop(monkeypatch):
    """Refuse a test's bus listener that HA would run in the executor.

    HA runs a listener that is neither ``@callback`` nor a coroutine as an executor
    job: it lands on a worker thread some time after the event fires, so what it
    records can arrive out of order or after the test has already asserted.
    """
    original = EventBus.async_listen

    def _checked(self, event_type, listener, *args, **kwargs):
        module = getattr(listener, "__module__", "") or ""
        if (module.startswith("tests")
                and HassJob(listener).job_type is HassJobType.Executor):
            raise AssertionError(
                f"test listener {listener!r} for {event_type!r} would run in the "
                "executor; wrap it in @callback")
        return original(self, event_type, listener, *args, **kwargs)

    monkeypatch.setattr(EventBus, "async_listen", _checked)
