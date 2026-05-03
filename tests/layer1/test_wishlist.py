import pytest
from tests.conftest import SAMPLE_MASTER_RESPONSE


async def test_list_wishlist_empty(client):
    r = await client.get("/api/wishlist")
    assert r.status_code == 200
    assert r.json() == []


async def test_add_wishlist_item(client, mock_discogs, mock_download_images):
    mock_get, _ = mock_discogs
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = SAMPLE_MASTER_RESPONSE

    r = await client.post("/api/wishlist", json={"master_id": "99999"})
    assert r.status_code == 201
    assert "id" in r.json()


async def test_list_wishlist_after_add(client, mock_discogs, mock_download_images):
    mock_get, _ = mock_discogs
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = SAMPLE_MASTER_RESPONSE

    await client.post("/api/wishlist", json={"master_id": "99999"})
    r = await client.get("/api/wishlist")
    items = r.json()
    assert len(items) == 1
    assert items[0]["artist"] == "Test Artist"
    assert items[0]["master_id"] == "99999"


async def test_add_duplicate_wishlist_item_returns_409(client, mock_discogs, mock_download_images):
    mock_get, _ = mock_discogs
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = SAMPLE_MASTER_RESPONSE

    await client.post("/api/wishlist", json={"master_id": "99999"})
    r = await client.post("/api/wishlist", json={"master_id": "99999"})
    assert r.status_code == 409


async def test_update_wishlist_notes(client, mock_discogs, mock_download_images):
    mock_get, _ = mock_discogs
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = SAMPLE_MASTER_RESPONSE

    item_id = (await client.post("/api/wishlist", json={"master_id": "99999"})).json()["id"]
    r = await client.put(f"/api/wishlist/{item_id}", json={"notes": "Want this one"})
    assert r.status_code == 200

    items = (await client.get("/api/wishlist")).json()
    assert items[0]["notes"] == "Want this one"


async def test_mark_wishlist_fulfilled(client, mock_discogs, mock_download_images):
    mock_get, _ = mock_discogs
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = SAMPLE_MASTER_RESPONSE

    item_id = (await client.post("/api/wishlist", json={"master_id": "99999"})).json()["id"]
    await client.put(f"/api/wishlist/{item_id}", json={"fulfilled": True})

    r = await client.get("/api/wishlist")
    assert r.json() == []


async def test_list_wishlist_include_fulfilled(client, mock_discogs, mock_download_images):
    mock_get, _ = mock_discogs
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = SAMPLE_MASTER_RESPONSE

    item_id = (await client.post("/api/wishlist", json={"master_id": "99999"})).json()["id"]
    await client.put(f"/api/wishlist/{item_id}", json={"fulfilled": True})

    r = await client.get("/api/wishlist?show_fulfilled=true")
    assert len(r.json()) == 1


async def test_delete_wishlist_item(client, mock_discogs, mock_download_images):
    mock_get, _ = mock_discogs
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = SAMPLE_MASTER_RESPONSE

    item_id = (await client.post("/api/wishlist", json={"master_id": "99999"})).json()["id"]
    r = await client.delete(f"/api/wishlist/{item_id}")
    assert r.status_code == 200

    assert (await client.get("/api/wishlist")).json() == []
