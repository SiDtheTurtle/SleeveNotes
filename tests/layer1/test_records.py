import sqlite3
import pytest
import app as app_module
from tests.conftest import SAMPLE_RECORD


SAMPLE_REFRESH_RELEASE = {
    "artists": [{"name": "Updated Artist"}],
    "title": "Updated Title",
    "labels": [{"name": "Updated Label", "catno": "UPD-001"}],
    "year": 2024,
    "formats": [{"name": "Vinyl", "descriptions": ["LP"]}],
    "tracklist": [],
    "images": [],
}

SAMPLE_REFRESH_STATS = {
    "lowest_price": {"value": "20.00"},
}


async def _refresh_side_effect(client, url, **kwargs):
    from unittest.mock import MagicMock
    mock = MagicMock()
    if "marketplace/stats" in url:
        mock.status_code = 200
        mock.json.return_value = SAMPLE_REFRESH_STATS
    else:
        mock.status_code = 200
        mock.json.return_value = SAMPLE_REFRESH_RELEASE
    return mock


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


# ── Refresh ───────────────────────────────────────────────────────────────────

async def test_refresh_record_updates_discogs_fields(client, mock_discogs, mock_download_images):
    record_id = (await client.post("/api/records", json=SAMPLE_RECORD)).json()["id"]
    mock_get, _ = mock_discogs
    mock_get.side_effect = _refresh_side_effect

    r = await client.post(f"/api/records/{record_id}/refresh")
    assert r.status_code == 200

    records = (await client.get("/api/records")).json()
    assert records[0]["artist"] == "Updated Artist"
    assert records[0]["title"] == "Updated Title"
    assert records[0]["label"] == "Updated Label"
    assert records[0]["valuation"] == 20.0


async def test_refresh_record_preserves_user_fields(client, mock_discogs, mock_download_images):
    record_id = (await client.post("/api/records", json={
        **SAMPLE_RECORD, "notes": "My note", "retailer": "Juno", "price": 15.0,
    })).json()["id"]
    mock_get, _ = mock_discogs
    mock_get.side_effect = _refresh_side_effect

    await client.post(f"/api/records/{record_id}/refresh")

    record = (await client.get("/api/records")).json()[0]
    assert record["notes"] == "My note"
    assert record["retailer"] == "Juno"
    assert record["price"] == 15.0


async def test_refresh_record_not_found(client, mock_discogs, mock_download_images):
    r = await client.post("/api/records/9999/refresh")
    assert r.status_code == 404


# ── Set cover ────────────────────────────────────────────────────────────────

async def test_set_cover_updates_cover_file(client):
    record_id = (await client.post("/api/records", json=SAMPLE_RECORD)).json()["id"]
    with sqlite3.connect(app_module.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO images (discogs_id, filename, seq, is_cover) VALUES (?, ?, ?, ?)",
            ("r99999999", "r99999999_01.jpeg", 1, 1),
        )
        conn.execute(
            "INSERT INTO images (discogs_id, filename, seq, is_cover) VALUES (?, ?, ?, ?)",
            ("r99999999", "r99999999_02.jpeg", 2, 0),
        )

    r = await client.post(
        f"/api/records/{record_id}/set-cover",
        json={"filename": "r99999999_02.jpeg"},
    )
    assert r.status_code == 200

    record = (await client.get("/api/records")).json()[0]
    assert record["cover_file"] == "r99999999_02.jpeg"

    with sqlite3.connect(app_module.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT filename, is_cover FROM images WHERE discogs_id = 'r99999999' ORDER BY seq"
        ).fetchall()
    assert rows[0][1] == 0
    assert rows[1][1] == 1


async def test_set_cover_not_found(client):
    r = await client.post("/api/records/9999/set-cover", json={"filename": "x.jpeg"})
    assert r.status_code == 404
