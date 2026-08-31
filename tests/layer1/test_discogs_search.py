import pytest


SAMPLE_SEARCH_RESPONSE = {
    "results": [
        {
            "id": 12345678,
            "title": "Test Artist - Test Album",
            "year": "2019",
            "country": "UK",
            "label": ["Some Label", "Some Label"],
            "catno": "ABC123",
            "format": ["Vinyl", "LP", "Album"],
            "thumb": "https://img.discogs.com/thumb.jpg",
        }
    ]
}


async def test_search_by_barcode(client, mock_discogs):
    mock_get, _ = mock_discogs
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = SAMPLE_SEARCH_RESPONSE

    r = await client.get("/api/discogs/search?barcode=602577603679")
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 1
    assert results[0] == {
        "id": "12345678",
        "title": "Test Artist - Test Album",
        "year": "2019",
        "country": "UK",
        "label": "Some Label",
        "catno": "ABC123",
        "format": "Vinyl, LP, Album",
        "thumb": "https://img.discogs.com/thumb.jpg",
    }


async def test_search_by_q(client, mock_discogs):
    mock_get, _ = mock_discogs
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = SAMPLE_SEARCH_RESPONSE

    r = await client.get("/api/discogs/search?q=test+album")
    assert r.status_code == 200
    assert r.json()[0]["id"] == "12345678"


async def test_search_missing_params_returns_400(client, mock_discogs):
    r = await client.get("/api/discogs/search")
    assert r.status_code == 400


async def test_search_propagates_discogs_error_status(client, mock_discogs):
    mock_get, _ = mock_discogs
    mock_get.return_value.status_code = 502
    mock_get.return_value.json.return_value = {}

    r = await client.get("/api/discogs/search?barcode=602577603679")
    assert r.status_code == 502


async def test_search_empty_results(client, mock_discogs):
    mock_get, _ = mock_discogs
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"results": []}

    r = await client.get("/api/discogs/search?barcode=000000000000")
    assert r.status_code == 200
    assert r.json() == []


async def test_search_result_missing_optional_fields(client, mock_discogs):
    mock_get, _ = mock_discogs
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "results": [{"id": 999, "title": "Bare Result"}]
    }

    r = await client.get("/api/discogs/search?q=bare")
    assert r.status_code == 200
    row = r.json()[0]
    assert row == {
        "id": "999",
        "title": "Bare Result",
        "year": None,
        "country": "",
        "label": "",
        "catno": "",
        "format": "",
        "thumb": "",
    }
