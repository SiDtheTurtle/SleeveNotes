import sqlite3
import pytest
from unittest.mock import MagicMock
import app as app_module
from tests.conftest import SAMPLE_RECORD


SAMPLE_RELEASE_RESPONSE = {
    "artists": [{"name": "Test Artist"}],
    "title": "Test Album",
    "labels": [{"name": "Test Label", "catno": "TEST-001"}],
    "year": 2000,
    "formats": [{"name": "Vinyl", "descriptions": ["LP"]}],
    "tracklist": [],
    "images": [],
    "master_id": 99999,
}

SAMPLE_STATS_RESPONSE = {
    "lowest_price": {"value": "12.50"},
}


async def _side_effect(client, url, **kwargs):
    mock = MagicMock()
    if "marketplace/stats" in url:
        mock.status_code = 200
        mock.json.return_value = SAMPLE_STATS_RESPONSE
    else:
        mock.status_code = 200
        mock.json.return_value = SAMPLE_RELEASE_RESPONSE
    return mock


async def test_fetch_discogs_returns_metadata(client, mock_discogs, mock_download_images):
    mock_get, _ = mock_discogs
    mock_get.side_effect = _side_effect

    r = await client.get("/api/discogs/r99999999")
    assert r.status_code == 200
    data = r.json()
    assert data["discogs_id"] == "r99999999"
    assert data["artist"] == "Test Artist"
    assert data["title"] == "Test Album"
    assert data["label"] == "Test Label"
    assert data["cat_no"] == "TEST-001"
    assert data["year"] == 2000
    assert data["valuation"] == 12.5


async def test_fetch_discogs_accepts_id_without_r_prefix(client, mock_discogs, mock_download_images):
    mock_get, _ = mock_discogs
    mock_get.side_effect = _side_effect

    r = await client.get("/api/discogs/99999999")
    assert r.status_code == 200
    assert r.json()["discogs_id"] == "r99999999"


async def test_fetch_discogs_wishlist_match(client, mock_discogs, mock_download_images):
    with sqlite3.connect(app_module.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO wishlist (master_id, artist, title, cover_file, notes, year, fulfilled)"
            " VALUES (?, ?, ?, ?, ?, ?, 0)",
            ("99999", "Test Artist", "Test Album", "", "Want this", 2000),
        )

    mock_get, _ = mock_discogs
    mock_get.side_effect = _side_effect

    r = await client.get("/api/discogs/99999999")
    assert r.status_code == 200
    match = r.json()["wishlist_match"]
    assert match is not None
    assert match["notes"] == "Want this"


async def test_fetch_discogs_no_wishlist_match(client, mock_discogs, mock_download_images):
    mock_get, _ = mock_discogs
    mock_get.side_effect = _side_effect

    r = await client.get("/api/discogs/99999999")
    assert r.status_code == 200
    assert r.json()["wishlist_match"] is None


async def test_fetch_discogs_propagates_error_status(client, mock_discogs, mock_download_images):
    mock_get, _ = mock_discogs

    async def _404_side_effect(client, url, **kwargs):
        mock = MagicMock()
        mock.status_code = 404
        mock.json.return_value = {}
        return mock

    mock_get.side_effect = _404_side_effect

    r = await client.get("/api/discogs/99999999")
    assert r.status_code == 404
