import json

import pytest

from app.realtime import ConnectionManager


class FakeWebSocket:
    def __init__(self, fail_on_send=False):
        self.accepted = False
        self.sent: list[str] = []
        self._fail_on_send = fail_on_send

    async def accept(self):
        self.accepted = True

    async def send_text(self, message: str):
        if self._fail_on_send:
            raise RuntimeError("connection closed")
        self.sent.append(message)


@pytest.mark.asyncio
async def test_connect_accepts_and_registers_websocket():
    manager = ConnectionManager()
    ws = FakeWebSocket()

    await manager.connect(ws)

    assert ws.accepted is True
    assert ws in manager._connections


@pytest.mark.asyncio
async def test_broadcast_sends_json_payload_to_all_connections():
    manager = ConnectionManager()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    await manager.connect(ws1)
    await manager.connect(ws2)

    await manager.broadcast("candidate_new", {"candidate_id": 42})

    expected = json.dumps({"type": "candidate_new", "payload": {"candidate_id": 42}})
    assert ws1.sent == [expected]
    assert ws2.sent == [expected]


@pytest.mark.asyncio
async def test_disconnect_removes_websocket():
    manager = ConnectionManager()
    ws = FakeWebSocket()
    await manager.connect(ws)

    await manager.disconnect(ws)

    assert ws not in manager._connections


@pytest.mark.asyncio
async def test_broadcast_drops_dead_connections_without_raising():
    manager = ConnectionManager()
    dead = FakeWebSocket(fail_on_send=True)
    alive = FakeWebSocket()
    await manager.connect(dead)
    await manager.connect(alive)

    await manager.broadcast("ping", {})

    assert dead not in manager._connections
    assert alive in manager._connections
    assert alive.sent
