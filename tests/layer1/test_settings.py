import pytest
import app as app_module


async def test_get_settings_returns_defaults(client):
    r = await client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    for key in app_module.SETTINGS_DEFAULTS:
        assert key in data


async def test_get_settings_excludes_api_key(client):
    r = await client.get("/api/settings")
    assert "api_key" not in r.json()


async def test_update_setting(client):
    r = await client.put("/api/settings/currency", json={"value": "$"})
    assert r.status_code == 200

    r = await client.get("/api/settings")
    assert r.json()["currency"] == "$"


async def test_update_setting_persists_across_requests(client):
    await client.put("/api/settings/clean_artists", json={"value": "false"})
    r = await client.get("/api/settings")
    assert r.json()["clean_artists"] == "false"
