import pytest

from steam_browser import web as web_module


@pytest.fixture
def client():
    web_module.app.config["STEAM_BROWSER_API_KEY"] = "test-key"
    web_module.app.config["TESTING"] = True
    with web_module.app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_state():
    """web.py keeps refresh state in module-level globals shared by every
    request, so tests must reset them or bleed state into each other.
    """
    with web_module._state_lock:
        web_module._state["servers"] = []
        web_module._state["status"] = "idle"
        web_module._state["error"] = None
        web_module._state["last_updated"] = None
        web_module._state["candidate_count"] = 0
    web_module._cancel_event.clear()
    web_module.app.config["DEV_MODE"] = False
    # The limiter's in-memory counters are shared across the whole pytest
    # run (module-level app), so leaving it on would make tests fail on
    # accumulated request volume rather than anything they assert.
    web_module.limiter.enabled = False
    yield
