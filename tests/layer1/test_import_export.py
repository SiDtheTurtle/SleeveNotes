import io
import zipfile
import pytest
import app as app_module
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


# ── Remaining exports ────────────────────────────────────────────────────────

async def test_export_images_returns_zip(client):
    r = await client.get("/api/export/images")
    assert r.status_code == 200
    assert "application/zip" in r.headers["content-type"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        # No images on disk — zip should be valid (possibly empty)
        assert isinstance(z.namelist(), list)


async def test_export_all_returns_zip_with_sql(client):
    r = await client.get("/api/export/all")
    assert r.status_code == 200
    assert "application/zip" in r.headers["content-type"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert any(n.endswith(".sql") for n in z.namelist())


# ── Import DB ────────────────────────────────────────────────────────────────

async def test_import_db_round_trips(client, monkeypatch):
    await client.post("/api/records", json=SAMPLE_RECORD)
    export = await client.get("/api/export/db")
    assert export.status_code == 200

    # Redirect to a non-existent sibling path so import_db's unlink(missing_ok=True)
    # is a no-op on both Windows and Linux, and executescript builds a fresh DB.
    monkeypatch.setattr(app_module, "DB_PATH", app_module.DB_PATH.parent / "restored.db")

    r = await client.post(
        "/api/import/db",
        files={"file": ("backup.zip", export.content, "application/zip")},
    )
    assert r.status_code == 200

    records = (await client.get("/api/records")).json()
    assert len(records) == 1
    assert records[0]["artist"] == "Test Artist"


# ── Import images ────────────────────────────────────────────────────────────

async def test_import_images_returns_count(client):
    import app as app_module

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("r99999999_01.jpeg", b"fake image data")
    buf.seek(0)

    r = await client.post(
        "/api/import/images",
        files={"file": ("images.zip", buf.read(), "application/zip")},
    )
    assert r.status_code == 200
    assert r.json()["imported"] == 1
    assert (app_module.IMAGES_DIR / "r99999999_01.jpeg").exists()


# ── Import all ───────────────────────────────────────────────────────────────

async def test_import_all_round_trips(client, monkeypatch):
    await client.post("/api/records", json=SAMPLE_RECORD)
    export = await client.get("/api/export/all")
    assert export.status_code == 200

    monkeypatch.setattr(app_module, "DB_PATH", app_module.DB_PATH.parent / "restored.db")

    r = await client.post(
        "/api/import/all",
        files={"file": ("backup.zip", export.content, "application/zip")},
    )
    assert r.status_code == 200

    records = (await client.get("/api/records")).json()
    assert len(records) == 1
    assert records[0]["artist"] == "Test Artist"
