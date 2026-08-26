import os
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

os.environ.setdefault("SN_DATA_DIR", "/tmp/sleevenotes-tests")

import app as app_module


@pytest.fixture
async def client(tmp_path, monkeypatch):
    """Isolated FastAPI test client backed by a fresh SQLite DB per test."""
    db_path = tmp_path / "test.db"
    images_dir = tmp_path / "images"
    monkeypatch.setattr(app_module, "DB_PATH", db_path)
    monkeypatch.setattr(app_module, "IMAGES_DIR", images_dir)
    monkeypatch.setattr(app_module, "_cached_api_key", None)
    app_module.init_db()
    async with AsyncClient(
        transport=ASGITransport(app=app_module.app),
        base_url="http://test",
    ) as ac:
        yield ac


def _make_discogs_response(status_code=200, json_data=None):
    """Build a mock httpx Response-like object."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data or {}
    return mock


@pytest.fixture
def mock_discogs(mocker):
    """Patch discogs_get and discogs_post. Returns (mock_get, mock_post)."""
    mock_get = mocker.patch("app.discogs_get", new_callable=AsyncMock)
    mock_post = mocker.patch("app.discogs_post", new_callable=AsyncMock)
    mock_get.return_value = _make_discogs_response()
    mock_post.return_value = _make_discogs_response()
    return mock_get, mock_post


@pytest.fixture
def mock_download_images(mocker):
    """Patch download_all_images to skip actual HTTP image fetching."""
    mock = mocker.patch("app.download_all_images", new_callable=AsyncMock)
    mock.return_value = []
    return mock


# ── Shared fixture data ───────────────────────────────────────────────────────

SAMPLE_RECORD = {
    "discogs_id": "r99999999",
    "artist": "Test Artist",
    "title": "Test Album",
    "label": "Test Label",
    "cat_no": "TEST-001",
    "year": 2000,
    "format": "Vinyl, LP",
    "cover_file": "",
    "is_new": None,
    "curr_cond": "NM",
    "sleeve_cond": "NM",
    "retailer": "",
    "order_ref": "",
    "purchase_date": "",
    "price": 0,
    "pp": 0,
    "notes": "",
    "valuation": 0,
}

SAMPLE_MASTER_RESPONSE = {
    "id": 99999,
    "title": "Test Album",
    "year": 2000,
    "genres": ["Electronic"],
    "styles": ["Techno"],
    "lowest_price": 9.99,
    "num_for_sale": 5,
    "artists": [{"name": "Test Artist"}],
    "images": [],
}
