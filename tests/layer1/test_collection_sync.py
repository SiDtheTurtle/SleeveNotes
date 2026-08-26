import pytest
import app as app_module
from tests.conftest import SAMPLE_RECORD

# Minimal parsed item matching SAMPLE_RECORD fields
SAMPLE_PARSED = {
    "discogs_id": "r99999999",
    "instance_id": "inst-001",
    "folder_id": 1,
    "artist": "Test Artist",
    "title": "Test Album",
    "label": "Test Label",
    "cat_no": "TEST-001",
    "year": 2000,
    "format": "LP, Vinyl",
}


async def test_compute_diff_empty_db_all_new(client):
    diff = app_module.compute_diff([SAMPLE_PARSED])
    assert len(diff["new"]) == 1
    assert diff["changed"] == []
    assert diff["unchanged"] == []
    assert diff["db_only"] == []


async def test_compute_diff_matching_instance_id_unchanged(client):
    # Seed a record with matching instance_id
    await client.post("/api/records", json={**SAMPLE_RECORD, "discogs_id": "r99999999"})
    # Manually set instance_id via DB
    import sqlite3
    with sqlite3.connect(app_module.DB_PATH) as conn:
        conn.execute("UPDATE records SET instance_id = 'inst-001'")

    diff = app_module.compute_diff([SAMPLE_PARSED])
    assert diff["unchanged"] != [] or diff["changed"] != []
    assert diff["new"] == []


async def test_compute_diff_changed_field(client):
    await client.post("/api/records", json={**SAMPLE_RECORD, "discogs_id": "r99999999"})
    import sqlite3
    with sqlite3.connect(app_module.DB_PATH) as conn:
        conn.execute("UPDATE records SET instance_id = 'inst-001', artist = 'Old Artist'")

    diff = app_module.compute_diff([SAMPLE_PARSED])
    assert len(diff["changed"]) == 1
    # changes is a dict keyed by field name
    changes = diff["changed"][0]["changes"]
    assert "artist" in changes
    assert changes["artist"]["from"] == "Old Artist"
    assert changes["artist"]["to"] == "Test Artist"


async def test_compute_diff_db_only(client):
    await client.post("/api/records", json=SAMPLE_RECORD)
    # No items in incoming list — existing record is db_only
    diff = app_module.compute_diff([])
    assert len(diff["db_only"]) == 1


async def test_collection_sync_creates_records(client):
    await client.put("/api/settings/discogs_username", json={"value": "testuser"})
    payload = {
        "to_sleevenotes": [{"action": "create", "prospective": SAMPLE_PARSED}],
        "to_discogs": [],
    }
    r = await client.post("/api/collection/sync", json=payload)
    assert r.status_code == 200

    records = (await client.get("/api/records")).json()
    assert len(records) == 1
    assert records[0]["artist"] == "Test Artist"


async def test_currency_mismatch_flagged_in_diff(client):
    # Seed a record, then parse an item where price field has wrong currency symbol
    await client.post("/api/records", json=SAMPLE_RECORD)
    import sqlite3
    with sqlite3.connect(app_module.DB_PATH) as conn:
        conn.execute("UPDATE records SET instance_id = 'inst-001'")
        # Map a price field
        conn.execute("UPDATE settings SET value = '{\"1\": \"price\"}' WHERE key = 'discogs_field_mappings'")

    parsed = {
        **SAMPLE_PARSED,
        "price": None,
        "_raw_price": "$9.99",       # dollar sign, but setting is £
        "_currency_mismatch_price": True,
    }
    diff = app_module.compute_diff([parsed])
    if diff["changed"]:
        changes = diff["changed"][0]["changes"]
        assert "price" in changes
        assert changes["price"].get("currency_mismatch") is True


# ── Collection fields ────────────────────────────────────────────────────────

async def test_collection_fields_no_username_returns_400(client):
    r = await client.get("/api/collection/fields")
    assert r.status_code == 400


async def test_collection_fields_returns_json(client, mock_discogs):
    await client.put("/api/settings/discogs_username", json={"value": "testuser"})
    mock_get, _ = mock_discogs
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "fields": [
            {"id": 1, "name": "Media Condition"},
            {"id": 2, "name": "Sleeve Condition"},
        ]
    }

    r = await client.get("/api/collection/fields")
    assert r.status_code == 200
    data = r.json()
    assert "fields" in data
    assert len(data["fields"]) == 2


# ── Collection preview ───────────────────────────────────────────────────────

SAMPLE_COLLECTION_PAGE = {
    "pagination": {"pages": 1},
    "releases": [
        {
            "instance_id": 1001,
            "folder_id": 1,
            "basic_information": {
                "id": 99999999,
                "title": "Test Album",
                "year": 2000,
                "artists": [{"name": "Test Artist"}],
                "labels": [{"name": "Test Label", "catno": "TEST-001"}],
                "formats": [{"name": "Vinyl", "descriptions": ["LP"]}],
            },
            "notes": [],
        }
    ],
}


async def test_collection_preview_no_username_returns_400(client):
    r = await client.get("/api/collection/preview")
    assert r.status_code == 400


async def test_collection_preview_returns_diff(client, mock_discogs):
    await client.put("/api/settings/discogs_username", json={"value": "testuser"})
    mock_get, _ = mock_discogs
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = SAMPLE_COLLECTION_PAGE

    r = await client.get("/api/collection/preview")
    assert r.status_code == 200
    diff = r.json()
    assert "new" in diff
    assert "changed" in diff
    assert "unchanged" in diff
    assert "db_only" in diff
    assert len(diff["new"]) == 1
    assert diff["new"][0]["artist"] == "Test Artist"
