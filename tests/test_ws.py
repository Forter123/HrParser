from app.realtime import manager


def test_websocket_connect_and_disconnect_updates_manager(client):
    manager._connections.clear()

    with client.websocket_connect("/ws/feed") as ws:
        assert len(manager._connections) == 1
        ws.close()

    assert len(manager._connections) == 0
