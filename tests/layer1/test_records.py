import pytest
from tests.conftest import SAMPLE_RECORD


async def test_list_records_empty(client):
    r = await client.get("/api/records")
    assert r.status_code == 200
    assert r.json() == []


async def test_create_record(client):
    r = await client.post("/api/records", json=SAMPLE_RECORD)
    assert r.status_code == 201
    assert "id" in r.json()


async def test_list_records_after_create(client):
    await client.post("/api/records", json=SAMPLE_RECORD)
    r = await client.get("/api/records")
    records = r.json()
    assert len(records) == 1
    assert records[0]["artist"] == "Test Artist"
    assert records[0]["title"] == "Test Album"


async def test_update_record(client):
    record_id = (await client.post("/api/records", json=SAMPLE_RECORD)).json()["id"]
    r = await client.put(f"/api/records/{record_id}", json={**SAMPLE_RECORD, "notes": "Updated note"})
    assert r.status_code == 200

    records = (await client.get("/api/records")).json()
    assert records[0]["notes"] == "Updated note"


async def test_delete_record(client):
    record_id = (await client.post("/api/records", json=SAMPLE_RECORD)).json()["id"]
    r = await client.delete(f"/api/records/{record_id}")
    assert r.status_code == 200

    records = (await client.get("/api/records")).json()
    assert records == []


async def test_deleted_record_has_deleted_at(client, tmp_path, monkeypatch):
    import sqlite3, app as app_module
    record_id = (await client.post("/api/records", json=SAMPLE_RECORD)).json()["id"]
    await client.delete(f"/api/records/{record_id}")

    with sqlite3.connect(app_module.DB_PATH) as conn:
        row = conn.execute("SELECT deleted_at FROM records WHERE id = ?", (record_id,)).fetchone()
    assert row[0] is not None


async def test_create_multiple_records(client):
    for i in range(3):
        await client.post("/api/records", json={**SAMPLE_RECORD, "title": f"Album {i}"})
    records = (await client.get("/api/records")).json()
    assert len(records) == 3


async def test_get_tracklist_empty(client):
    record_id = (await client.post("/api/records", json=SAMPLE_RECORD)).json()["id"]
    r = await client.get(f"/api/records/{record_id}/tracklist")
    assert r.status_code == 200
    assert r.json() == []


async def test_get_images_empty(client):
    record_id = (await client.post("/api/records", json=SAMPLE_RECORD)).json()["id"]
    r = await client.get(f"/api/records/{record_id}/images")
    assert r.status_code == 200
    assert r.json() == []
