import pytest
import app as app_module
from tests.conftest import SAMPLE_RECORD


async def test_format_deletes_records(client):
    await client.post("/api/records", json=SAMPLE_RECORD)
    r = await client.post("/api/admin/format")
    assert r.status_code == 200
    assert (await client.get("/api/records")).json() == []


async def test_format_preserves_settings(client):
    await client.put("/api/settings/currency", json={"value": "$"})
    await client.post("/api/records", json=SAMPLE_RECORD)
    await client.post("/api/admin/format")
    settings = (await client.get("/api/settings")).json()
    assert settings["currency"] == "$"


async def test_factory_reset_deletes_records(client):
    await client.post("/api/records", json=SAMPLE_RECORD)
    r = await client.post("/api/admin/factory-reset")
    assert r.status_code == 200
    assert (await client.get("/api/records")).json() == []


async def test_factory_reset_restores_default_settings(client):
    await client.put("/api/settings/currency", json={"value": "$"})
    await client.post("/api/admin/factory-reset")
    settings = (await client.get("/api/settings")).json()
    assert settings["currency"] == app_module.SETTINGS_DEFAULTS["currency"]


async def test_clear_images_returns_ok(client):
    r = await client.post("/api/admin/clear-images")
    assert r.status_code == 200
