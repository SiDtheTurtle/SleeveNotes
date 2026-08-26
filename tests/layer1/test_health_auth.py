import pytest


async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_auth_status_unconfigured(client):
    r = await client.get("/api/auth/status")
    assert r.status_code == 200
    assert r.json()["configured"] is False


async def test_protected_endpoint_no_key_set_allows_request(client):
    # With no api_key configured, all requests pass through
    r = await client.get("/api/records")
    assert r.status_code == 200


async def test_protected_endpoint_blocked_without_header(client):
    await client.put("/api/settings/api_key", json={"value": "secret123"})
    r = await client.get("/api/records")
    assert r.status_code == 401


async def test_protected_endpoint_allowed_with_correct_key(client):
    await client.put("/api/settings/api_key", json={"value": "secret123"})
    r = await client.get("/api/records", headers={"X-API-Key": "secret123"})
    assert r.status_code == 200


async def test_health_bypasses_auth(client):
    await client.put("/api/settings/api_key", json={"value": "secret123"})
    r = await client.get("/api/health")
    assert r.status_code == 200


async def test_auth_status_bypasses_auth(client):
    await client.put("/api/settings/api_key", json={"value": "secret123"})
    r = await client.get("/api/auth/status")
    assert r.status_code == 200
    assert r.json()["configured"] is True
