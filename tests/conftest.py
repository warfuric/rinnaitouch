"""Shared fixtures: enable custom integrations and point the library at a simulated unit."""
import socket

import pytest

from pyrinnaitouch import connection as rinnai_connection
from pyrinnaitouch.connection import RinnaiConnection
from pyrinnaitouch.simulator import FakeRinnaiUnit
from pyrinnaitouch.system import RinnaiSystem


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def closed_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations, socket_enabled):
    """Let the harness load custom_components/rinnaitouch and talk to loopback sockets."""
    yield


@pytest.fixture(autouse=True)
async def _clean_library_registry():
    RinnaiSystem.instances.clear()
    RinnaiConnection._active.clear()  # pylint: disable=protected-access
    yield
    for ip_address in list(RinnaiSystem.instances):
        await RinnaiSystem.async_remove_instance(ip_address)
    RinnaiConnection._active.clear()  # pylint: disable=protected-access


@pytest.fixture(name="unit")
async def fixture_unit(monkeypatch):
    """A simulated unit on the loopback, with the library's default ports pointed at it."""
    unit = await FakeRinnaiUnit(
        udp_port=free_udp_port(), status_interval=0.1, broadcast_interval=0.1
    ).start()
    monkeypatch.setattr(rinnai_connection, "DEFAULT_TCP_PORT", unit.tcp_port)
    monkeypatch.setattr(rinnai_connection, "DEFAULT_UDP_PORT", unit.udp_port)
    yield unit
    await unit.stop()


@pytest.fixture(name="no_unit")
def fixture_no_unit(monkeypatch):
    """Nothing listening: the library's default ports point at closed loopback ports."""
    monkeypatch.setattr(rinnai_connection, "DEFAULT_TCP_PORT", closed_tcp_port())
    monkeypatch.setattr(rinnai_connection, "DEFAULT_UDP_PORT", free_udp_port())
