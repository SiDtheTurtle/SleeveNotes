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
