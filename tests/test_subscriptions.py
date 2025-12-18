import pytest


@pytest.mark.asyncio
async def test_subscribe_then_unsubscribe_success(agent_client):
    """Full flow: subscribe once, then successfully unsubscribe.

    This goes through the Agent microservice /subscribe and /unsubscribe
    endpoints, which in turn use the in-memory SubscriptionService and
    (optionally) the DB-backed service.
    """
    payload = {
        "user_id": "SubUser1",
        "bus_id": "B1",
        "stop_id": "S1",
        "notify_before_sec": 300,
        "policy": {"notify_once": False, "delay_threshold": 900},
        "channel": "console",
    }

    # 1) Subscribe
    resp = await agent_client.post("/subscribe", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    sub = data.get("data") or data
    # We expect the service to echo back the subscription fields
    assert sub.get("user_id") == payload["user_id"]
    assert sub.get("bus_id") == payload["bus_id"]
    assert sub.get("stop_id") == payload["stop_id"]

    # 2) Unsubscribe
    resp_unsub = await agent_client.post(
        "/unsubscribe",
        params={
            "user_id": payload["user_id"],
            "bus_id": payload["bus_id"],
            "stop_id": payload["stop_id"],
        },
    )
    assert resp_unsub.status_code == 200
    data_unsub = resp_unsub.json()
    assert data_unsub.get("ok") is True
    msg = (data_unsub.get("data") or {}).get("message", "").lower()
    assert "unsubscribed" in msg


@pytest.mark.asyncio
async def test_duplicate_subscription_returns_conflict(agent_client):
    """Second subscription with same user/bus/stop should be rejected with 409."""
    payload = {
        "user_id": "SubUser2",
        "bus_id": "B2",
        "stop_id": "S2",
        "notify_before_sec": 300,
        "policy": {"notify_once": True, "delay_threshold": 600},
        "channel": "console",
    }

    # First subscribe should succeed
    resp1 = await agent_client.post("/subscribe", json=payload)
    assert resp1.status_code == 200

    # Second subscribe with same identifiers should return HTTP 409
    resp2 = await agent_client.post("/subscribe", json=payload)
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_unsubscribe_not_found(agent_client):
    """Unsubscribing a non-existent subscription should return 404."""
    resp = await agent_client.post(
        "/unsubscribe",
        params={"user_id": "NoSubUser", "bus_id": "B9", "stop_id": "S9"},
    )
    assert resp.status_code == 404
    data = resp.json()
    assert data.get("detail") == "Subscription not found"
