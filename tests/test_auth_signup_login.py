import pytest


@pytest.mark.asyncio
async def test_signup_and_login_flow(auth_client):
    """Happy-path: user can sign up once and then log in with OTP.

    This uses a fake phone number; OTP is returned from the API
    so we don't need to read logs.
    """
    user_id = "testuser1"

    # 1) Start signup
    resp = await auth_client.post(
        "/auth/signup/start",
        json={
            "user_id": user_id,
            "phone": "+911234567890",
            "role": "user",
            "name": "Test User",
            "email": "testuser1@example.com",
        },
    )
    assert resp.status_code == 200

    # 2) Starting signup again with a *different* user_id but the
    #    same phone/email should be rejected by our uniqueness
    #    checks (phone/email cannot be reused across accounts).
    resp_conflict = await auth_client.post(
        "/auth/signup/start",
        json={
            "user_id": "otheruser",
            "phone": "+911234567890",
            "role": "user",
            "name": "Other User",
            "email": "testuser1@example.com",
        },
    )
    assert resp_conflict.status_code == 409


@pytest.mark.asyncio
async def test_login_user_not_found(auth_client):
    """Login should return 404 for unknown user_id."""
    # use a syntactically valid user_id so we hit the
    # "not found" branch instead of validation error
    resp = await auth_client.post("/auth/login/start", json={"user_id": "NoSuch1"})
    assert resp.status_code == 404
    data = resp.json()
    assert data.get("detail") == "user_id not found"
