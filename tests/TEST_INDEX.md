# Test Index

Human-readable reference for the SleeveNotes regression test suite.  
Run with: `pytest tests/layer1/ -v` (Layer 1) or `pytest tests/layer2/ -m smoke -v` (Layer 2).

---

## Layer 1 — API Tests

Fast, isolated tests that run against the FastAPI app directly with a fresh in-memory SQLite database per test. No Docker, no Discogs account needed. Discogs API calls are mocked.

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

---

### Settings — `layer1/test_settings.py`

| Test | Purpose | Expected outcome |
|------|---------|-----------------|
| `test_get_settings_returns_defaults` | All default settings are present on a fresh install | GET returns all keys defined in `SETTINGS_DEFAULTS` |
| `test_get_settings_excludes_api_key` | The API key is never exposed through the settings endpoint | `api_key` absent from the GET response |
| `test_update_setting` | A setting can be changed and immediately retrieved | Currency updated to `$`; confirmed by subsequent GET |
| `test_update_setting_persists_across_requests` | Settings changes persist across separate requests | `clean_artists` set to `false`; confirmed by subsequent GET |

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

---

### Import & Export — `layer1/test_import_export.py`

| Test | Purpose | Expected outcome |
|------|---------|-----------------|
| `test_export_csv_headers` | CSV export responds with the correct content type and expected column headers | 200, `text/csv`, headers include `Artist`, `Title`, `release_id` |
| `test_export_csv_with_record` | A seeded record appears as a data row in the CSV | Exported CSV has exactly 2 lines: header + one record |
| `test_export_csv_excludes_deleted_records` | Soft-deleted records do not appear in the CSV export | Exported CSV has only the header row |
| `test_export_db_returns_zip` | Database export returns a zip archive containing a SQL dump | 200, `application/zip`, zip contains a `.sql` file |
| `test_import_csv_returns_diff` | Uploading a Discogs-format CSV produces a diff preview | Response includes a `new` bucket with the record from the CSV |
| `test_import_csv_existing_record_shows_unchanged` | A CSV record matching an existing DB record is not flagged as new | `new` bucket is empty; record appears in `unchanged` or `changed` |

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

## Layer 2 — Playwright Smoke Tests

Browser-level tests that run against a live Docker container on port 2027. Require `docker compose -f compose.test.yml up --build -d` and `tests/.env.test` with a test Discogs account. A golden database is loaded before each test.

Run with: `pytest tests/layer2/ -m smoke -v`

---

### Smoke Tests — `layer2/test_smoke.py`

| # | Test | Purpose | Expected outcome |
|---|------|---------|-----------------|
| 1 | `test_app_loads` | App shell renders correctly on load | KPI bar, toolbar, and main content area all visible |
| 2 | `test_add_record` | Full add-record flow via Discogs lookup | Enter a Discogs ID → Fetch populates fields → Save → modal closes |
| 3 | `test_collection_table_shows_records` | Collection table renders real data from the golden DB | At least one row visible in the table |
| 4 | `test_collection_tile_view` | Switching to tile view renders cover tiles | Tiles visible, each with an artist label |
| 5 | `test_column_sort` | Clicking a column header sorts the table | Artist header cycles asc → desc → cleared |
| 6 | `test_group_by_artist` | Group by artist toggle changes the table layout | Artist heading rows appear between record rows |
| 7 | `test_format_filter_bar` | Clicking a format tag filters the table | Only records matching the tag remain visible |
| 8 | `test_search_bar_filters` | Typing in the search bar filters records live | Non-matching search returns zero rows; clearing restores full list |
| 9 | `test_record_detail_modal` | Tapping a tile twice opens the detail modal | Modal visible with a non-empty title |
| 10 | `test_tracklist_tab` | Tracklist tab in the detail modal is reachable | Tracklist content area becomes visible |
| 11 | `test_edit_record` | Editing a record's notes persists the change | Updated notes visible in the table after save |
| 12 | `test_delete_record` | Deleting a record removes it from the table | Row count decrements by one |
| 13 | `test_kpi_total_count` | Total Records KPI shows a count greater than zero | KPI displays a positive integer |
| 14 | `test_kpi_collection_cost` | Collection Cost KPI displays a value | KPI text contains at least one digit |
| 15 | `test_wishlist_section_loads` | Switching to the Wishlist section works | Wishlist content visible; format bar hidden; Show Fulfilled toggle present |
| 16 | `test_wishlist_search_modal` | Search bar opens the master release search modal | Modal appears; results load after typing a query |
| 17 | `test_add_to_wishlist` | Adding a search result to the wishlist works | Item appears in the wishlist table |
| 18 | `test_wishlist_tile_view` | Wishlist tile view renders covers | Tiles visible in wishlist |
| 19 | `test_wishlist_detail_modal` | Clicking a wishlist item opens its detail modal | Modal visible with editable notes field |
| 20 | `test_mark_wishlist_fulfilled` | Marking an item fulfilled hides it from the list | Row count decrements; item gone from default view |
| 21 | `test_delete_wishlist_item` | Deleting a wishlist item removes it permanently | Row count decrements after delete |
| 22 | `test_settings_modal_open_close` | Settings modal opens and closes cleanly | Modal appears on gear click; disappears on Close |
| 23 | `test_settings_currency_change` | Changing the currency symbol takes effect immediately | KPI cost displays the new symbol after save |
| 24 | `test_export_csv_download` | Export CSV button triggers a file download | A `.csv` file download begins |
| 25 | `test_export_db_download` | Export Database button triggers a file download | A `.zip` file download begins |
| 26 | `test_import_csv_opens_diff_modal` | Uploading a CSV file opens the sync diff modal | Diff modal becomes visible |
| 27 | `test_collection_sync_preview` | Sync Collection in settings loads the preview modal | Diff modal and preview content visible |
| 28 | `test_auth_screen` | Setting an API key forces the auth screen on reload | Auth screen visible; entering the correct key loads the app |
