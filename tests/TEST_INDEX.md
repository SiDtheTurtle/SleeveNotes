# Test Index

Human-readable reference for the SleeveNotes API test suite.

Run from the repo root:

```bash
pytest
```

No container, no Discogs account, no environment variables. Each test gets a
fresh SQLite database; Discogs calls are mocked.

---

## Layer 1 — API Tests

Fast, isolated tests that run against the FastAPI app directly with a fresh SQLite database per test. No Docker, no Discogs account needed. Discogs API calls are mocked.

---

### Health & Auth — `layer1/test_health_auth.py`

| Test | Purpose | Expected outcome |
|------|---------|-----------------|
| `test_health` | Server is up and responsive | `GET /api/health` returns 200 with `{"status": "ok"}` |
| `test_auth_status_unconfigured` | Auth status correct when no key set | `GET /api/auth/status` returns `{"configured": false}` |
| `test_protected_endpoint_no_key_set_allows_request` | With no API key configured, all traffic passes through | `GET /api/records` returns 200 with no key set |
| `test_protected_endpoint_blocked_without_header` | Missing auth header is rejected when a key is configured | `GET /api/records` returns 401 with key set but no header |
| `test_protected_endpoint_allowed_with_correct_key` | Correct auth header grants access | `GET /api/records` returns 200 with correct `X-API-Key` |
| `test_health_bypasses_auth` | Health endpoint is always reachable regardless of auth | `GET /api/health` returns 200 even when auth is enforced |
| `test_auth_status_bypasses_auth` | Auth status endpoint is always reachable | `GET /api/auth/status` returns 200 and `{"configured": true}` when key is set |

---

### Records — `layer1/test_records.py`

| Test | Purpose | Expected outcome |
|------|---------|-----------------|
| `test_list_records_empty` | Empty collection returns an empty list, not an error | `GET /api/records` returns 200 with `[]` |
| `test_create_record` | A new record can be created | `POST /api/records` returns 201 with an `id` in the response |
| `test_list_records_after_create` | Created record appears in the collection | `GET /api/records` returns the record with correct artist and title |
| `test_update_record` | Record fields can be edited | `PUT /api/records/{id}` updates the field; confirmed by subsequent GET |
| `test_delete_record` | A record can be deleted | `DELETE /api/records/{id}` returns 200; record absent from subsequent GET |
| `test_deleted_record_has_deleted_at` | Deletion is soft — the row is kept in the DB with a timestamp | Deleted record has a non-null `deleted_at` value in the database |
| `test_create_multiple_records` | Multiple records can coexist | Three records created; GET returns all three |
| `test_get_tracklist_empty` | Tracklist endpoint works on a record with no cached tracks | Returns 200 with `[]` |
| `test_get_images_empty` | Images endpoint works on a record with no cached images | Returns 200 with `[]` |
| `test_refresh_record_updates_discogs_fields` | Refresh re-fetches and updates Discogs-sourced fields | Artist, title, label, valuation updated to values from mocked Discogs response |
| `test_refresh_record_preserves_user_fields` | Refresh does not touch user-entered fields | Notes, retailer, and price unchanged after refresh |
| `test_refresh_record_not_found` | Refresh on a non-existent record returns 404 | `POST /api/records/9999/refresh` returns 404 |
| `test_set_cover_updates_cover_file` | Setting a cover image updates `cover_file` and the `is_cover` flag | Record's `cover_file` updated; correct image row has `is_cover = 1` |
| `test_set_cover_not_found` | Set-cover on a non-existent record returns 404 | `POST /api/records/9999/set-cover` returns 404 |

---

### Settings — `layer1/test_settings.py`

| Test | Purpose | Expected outcome |
|------|---------|-----------------|
| `test_get_settings_returns_defaults` | All default settings are present on a fresh install | GET returns all keys defined in `SETTINGS_DEFAULTS` |
| `test_get_settings_excludes_api_key` | The API key is never exposed through the settings endpoint | `api_key` absent from the GET response |
| `test_update_setting` | A setting can be changed and immediately retrieved | Currency updated to `$`; confirmed by subsequent GET |
| `test_update_setting_persists_across_requests` | Settings changes persist across separate requests | `clean_artists` set to `false`; confirmed by subsequent GET |

---

### Discogs — `layer1/test_discogs.py`

*Both concurrent Discogs calls (`/releases/{id}` and `/marketplace/stats/{id}`) are mocked.*

| Test | Purpose | Expected outcome |
|------|---------|-----------------|
| `test_fetch_discogs_returns_metadata` | Full metadata is parsed and returned | Response includes correct artist, title, label, cat_no, year, and valuation |
| `test_fetch_discogs_accepts_id_without_r_prefix` | Bare numeric IDs are accepted as well as `r`-prefixed ones | `GET /api/discogs/99999999` returns same result as `r99999999` |
| `test_fetch_discogs_wishlist_match` | A matching unfulfilled wishlist item is included in the response | `wishlist_match` is non-null with correct notes when master_id matches |
| `test_fetch_discogs_no_wishlist_match` | No wishlist match returns null | `wishlist_match` is null when no matching item exists |
| `test_fetch_discogs_propagates_error_status` | A Discogs error status is forwarded to the caller | Mocked 404 from Discogs → endpoint returns 404 |

---

### Discogs Search — `layer1/test_discogs_search.py`

*`GET /api/discogs/search` — Discogs `/database/search` is mocked.*

| Test | Purpose | Expected outcome |
|------|---------|-----------------|
| `test_search_by_barcode` | A barcode query returns shaped release results | `?barcode=` → one row with `id`/`title`/`year`/`country`/`label`/`catno`/`format`/`thumb` in the documented shape |
| `test_search_by_q` | A free-text query hits the same endpoint | `?q=` → shaped results |
| `test_search_missing_params_returns_400` | Neither `barcode` nor `q` supplied is rejected | `GET /api/discogs/search` with no params returns 400 |
| `test_search_propagates_discogs_error_status` | A Discogs error status is forwarded to the caller | Mocked 502 from Discogs → endpoint returns 502 |
| `test_search_empty_results` | No matches returns an empty list, not an error | Mocked empty `results` → 200 with `[]` |
| `test_search_result_missing_optional_fields` | Results missing `label`/`format`/`thumb`/`year` don't crash the transform | Absent fields default to `""` / `None` |

---

### Wishlist — `layer1/test_wishlist.py`

*Discogs master fetch is mocked — no real API calls made.*

| Test | Purpose | Expected outcome |
|------|---------|-----------------|
| `test_list_wishlist_empty` | Empty wishlist returns an empty list | `GET /api/wishlist` returns 200 with `[]` |
| `test_add_wishlist_item` | A master release can be added to the wishlist | `POST /api/wishlist` returns 201 with an `id` |
| `test_list_wishlist_after_add` | Added item appears in the wishlist with correct metadata | GET returns the item with correct artist and master_id |
| `test_add_duplicate_wishlist_item_returns_409` | The same master cannot be added twice | Second POST with same master_id returns 409 |
| `test_update_wishlist_notes` | Notes on a wishlist item can be edited | PUT updates notes; confirmed by subsequent GET |
| `test_mark_wishlist_fulfilled` | Marking an item fulfilled hides it from the default list | Fulfilled item absent from `GET /api/wishlist` |
| `test_list_wishlist_include_fulfilled` | Fulfilled items are included when explicitly requested | `GET /api/wishlist?show_fulfilled=true` returns the fulfilled item |
| `test_delete_wishlist_item` | A wishlist item can be permanently deleted | DELETE returns 200; item absent from subsequent GET |
| `test_wishlist_search` | Discogs master search returns shaped results | Mocked Discogs search → response array with `master_id`, `title`, `year` |

---

### Collection Sync — `layer1/test_collection_sync.py`

| Test | Purpose | Expected outcome |
|------|---------|-----------------|
| `test_compute_diff_empty_db_all_new` | Items from Discogs not in the local DB are flagged as new | All items land in the `new` bucket |
| `test_compute_diff_matching_instance_id_unchanged` | Item already in DB with identical fields shows no changes | Item lands in `unchanged` (or `changed` if fields differ) — never `new` |
| `test_compute_diff_changed_field` | A field that differs between Discogs and the DB is detected | Item lands in `changed`; `changes.artist` shows the old and new values |
| `test_compute_diff_db_only` | Records in the DB not present in the Discogs list are surfaced | Record lands in `db_only` bucket |
| `test_collection_sync_creates_records` | Syncing a new item from Discogs creates a record in the DB | `POST /api/collection/sync` returns 200; record appears in collection |
| `test_currency_mismatch_flagged_in_diff` | A price field with the wrong currency symbol is flagged | Diff entry for `price` has `currency_mismatch: true` |
| `test_collection_fields_no_username_returns_400` | Fields endpoint requires a Discogs username to be configured | Returns 400 when `discogs_username` setting is empty |
| `test_collection_fields_returns_json` | Fields endpoint returns the Discogs custom field list | Mocked Discogs response passed through; `fields` array present |
| `test_collection_preview_no_username_returns_400` | Preview endpoint requires a Discogs username to be configured | Returns 400 when `discogs_username` setting is empty |
| `test_collection_preview_returns_diff` | Preview endpoint fetches the Discogs collection and returns a diff | Mocked single-page collection → diff with `new`/`changed`/`unchanged`/`db_only` keys |

---

### Import & Export — `layer1/test_import_export.py`

| Test | Purpose | Expected outcome |
|------|---------|-----------------|
| `test_export_csv_headers` | CSV export responds with the correct content type and expected column headers | 200, `text/csv`, headers include `Artist`, `Title`, `release_id` |
| `test_export_csv_with_record` | A seeded record appears as a data row in the CSV | Exported CSV has exactly 2 lines: header + one record |
| `test_export_csv_excludes_deleted_records` | Soft-deleted records do not appear in the CSV export | Exported CSV has only the header row |
| `test_export_db_returns_zip` | Database export returns a zip archive containing a SQL dump | 200, `application/zip`, zip contains a `.sql` file |
| `test_export_images_returns_zip` | Image export returns a valid zip (even with no images on disk) | 200, `application/zip`, valid zip file |
| `test_export_all_returns_zip_with_sql` | Combined backup export returns a zip containing a SQL dump | 200, `application/zip`, zip contains a `.sql` file |
| `test_import_csv_returns_diff` | Uploading a Discogs-format CSV produces a diff preview | Response includes a `new` bucket with the record from the CSV |
| `test_import_csv_existing_record_shows_unchanged` | A CSV record matching an existing DB record is not flagged as new | `new` bucket is empty; record appears in `unchanged` or `changed` |
| `test_import_db_round_trips` | A DB export zip can be re-imported to restore records | Records present after import match records before export |
| `test_import_images_returns_count` | Image import zip is unpacked and files written to the images directory | Returns `{"imported": 1}`; file exists on disk |
| `test_import_all_round_trips` | A combined backup zip can be re-imported to restore records | Records present after import match records before export |

---

### Admin — `layer1/test_admin.py`

| Test | Purpose | Expected outcome |
|------|---------|-----------------|
| `test_format_deletes_records` | Format wipes all records | `POST /api/admin/format` returns 200; collection is empty |
| `test_format_preserves_settings` | Format does not touch settings | Custom currency setting survives a format |
| `test_factory_reset_deletes_records` | Factory reset wipes all records | `POST /api/admin/factory-reset` returns 200; collection is empty |
| `test_factory_reset_restores_default_settings` | Factory reset restores all settings to their defaults | Currency (and all other settings) revert to `SETTINGS_DEFAULTS` values |
| `test_clear_images_returns_ok` | Clear image cache endpoint is reachable and succeeds | `POST /api/admin/clear-images` returns 200 |

---

### Image derivatives — `layer1/test_images.py`

| Test | Purpose | Expected outcome |
|------|---------|-----------------|
| `test_deriv_name_is_always_jpeg` | Derivative naming is a pure string transform | `r123_01.png` → `r123_01_s.jpeg` |
| `test_is_original_image_excludes_derivatives` | Backfill/manifest never treat `_m`/`_s` files as originals | `_m`/`_s`/non-image paths return `False` |
| `test_make_derivatives_creates_sized_siblings` | Full cover yields a 400px `_m` and 150px `_s` JPEG | Both files exist, correctly sized, smaller than the original |
| `test_make_derivatives_handles_non_jpeg_source` | RGBA/PNG source is flattened to RGB JPEG | `_m` opens as mode `RGB` |
| `test_make_derivatives_is_idempotent` | Re-running does not rewrite existing derivatives | mtime unchanged on second call |
| `test_backfill_skips_derivatives_and_counts_originals` | Startup/on-demand scan processes only originals | Returns `2` for two originals; makes `_m`/`_s` for each |
| `test_manifest_lists_only_derivatives` | Manifest endpoint returns derivative filenames | `GET /api/images/manifest` → `["r55_01_m.jpeg", "r55_01_s.jpeg"]` |
| `test_regenerate_thumbnails_endpoint` | Rebuild endpoint regenerates from originals | `POST /api/admin/regenerate-thumbnails` → `{"processed": 1}`; `_s` file created |
| `test_download_all_images_generates_derivatives` | Downloading a cover also writes its derivatives | `_m` and `_s` exist alongside `r12345_01.jpeg` |

---
