import io
import zipfile
import pytest
from tests.conftest import SAMPLE_RECORD

MINIMAL_CSV = (
    "Catalog#,Artist,Title,Label,Format,Released,release_id,"
    "CollectionFolder,Collection Media Condition,Collection Sleeve Condition\r\n"
    "TEST-001,Test Artist,Test Album,Test Label,Vinyl,2000,99999999,1,NM,NM\r\n"
)


async def test_export_csv_headers(client):
    r = await client.get("/api/export")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    header_line = r.text.splitlines()[0]
    assert "Artist" in header_line
    assert "Title" in header_line
    assert "release_id" in header_line


async def test_export_csv_with_record(client):
    await client.post("/api/records", json=SAMPLE_RECORD)
    r = await client.get("/api/export")
    lines = r.text.strip().splitlines()
    assert len(lines) == 2  # header + one record


async def test_export_csv_excludes_deleted_records(client):
    record_id = (await client.post("/api/records", json=SAMPLE_RECORD)).json()["id"]
    await client.delete(f"/api/records/{record_id}")
    r = await client.get("/api/export")
    lines = r.text.strip().splitlines()
    assert len(lines) == 1  # header only


async def test_export_db_returns_zip(client):
    r = await client.get("/api/export/db")
    assert r.status_code == 200
    assert "application/zip" in r.headers["content-type"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = z.namelist()
    assert any(n.endswith(".sql") for n in names)


async def test_import_csv_returns_diff(client):
    r = await client.post(
        "/api/import/csv",
        files={"file": ("discogs.csv", MINIMAL_CSV.encode(), "text/csv")},
    )
    assert r.status_code == 200
    diff = r.json()
    assert "new" in diff
    assert len(diff["new"]) == 1
    assert diff["new"][0]["artist"] == "Test Artist"


async def test_import_csv_existing_record_shows_unchanged(client):
    # Create the record first
    await client.post("/api/records", json={
        **SAMPLE_RECORD,
        "discogs_id": "r99999999",
        "instance_id": None,
    })
    r = await client.post(
        "/api/import/csv",
        files={"file": ("discogs.csv", MINIMAL_CSV.encode(), "text/csv")},
    )
    diff = r.json()
    assert diff["new"] == []
    assert len(diff["unchanged"]) + len(diff["changed"]) == 1
