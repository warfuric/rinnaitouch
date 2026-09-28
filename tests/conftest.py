"""Shared fixtures: enable custom integrations and keep the library's threads off the network."""
import threading
import time

import pytest

from pyrinnaitouch.pollconnection import RinnaiPollConnection
from pyrinnaitouch.system import RinnaiSystem


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let the harness load custom_components/rinnaitouch."""
    yield


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Never open the real socket thread; setup only needs the library object."""
    started = []
    monkeypatch.setattr(
        RinnaiPollConnection, "start_thread", lambda self: started.append(self)
    )
    RinnaiPollConnection.clients.clear()
    RinnaiSystem.instances.clear()
    yield started
    # Stop every consumer thread the tests created so the harness's lingering-thread
    # check sees a clean slate.
    for ip_address in list(RinnaiSystem.instances):
        RinnaiSystem.remove_instance(ip_address)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and any(
        t.name == "RinnaiSystem.poll_loop" for t in threading.enumerate()
    ):
        time.sleep(0.02)
    RinnaiPollConnection.clients.clear()
