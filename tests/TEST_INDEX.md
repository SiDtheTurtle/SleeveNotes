# Test Index

Human-readable reference for the SleeveNotes regression test suite.  
Run with: `pytest tests/layer1/ -v` (Layer 1) or `pytest tests/layer2/ -m smoke -v` (Layer 2).

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

## Layer 2 — Playwright Smoke Tests

Browser-level tests that run against the local dev container on port 2026. Require `tests/.env.test` with test credentials. All tests live in a single sequential journey in `layer2/test_smoke.py`.

Run with: `./tests/run-first-run.sh [start]` — accepts an optional start number to resume mid-run.

---

### First-run Tests — `layer2/test_smoke.py` (tests 1–4)

Require `--full-reset`. Test the initial setup flow on a blank container with no API key or credentials configured.

| # | Test | Purpose | Expected outcome |
|---|------|---------|-----------------|
| 1 | `test_first_run_auth_prompt` | Blank container shows the initial setup screen | Auth screen visible with "Choose an access key" heading |
| 2 | `test_first_run_set_api_key` | Setting an API key via the setup screen loads the app | App shell loads with empty collection after key is submitted |
| 3 | `test_first_run_discogs_credentials` | Entering Discogs credentials and saving triggers a live API call | Field mapping section becomes visible; no error shown |
| 4 | `test_first_run_field_mappings` | Setting all 9 custom field mappings persists after close and reopen | Each dropdown retains its saved value on reopen |

**Status: all 4 passing ✅**

---

### Collection & feature suite — `layer2/test_smoke.py` (tests 5–20)

Golden DB (`tests/fixtures/golden.zip`) restored via `/api/import/all` before test 5. Tests accumulate on that state.

| # | Test | Purpose | Expected outcome |
|---|------|---------|-----------------|
| 5 | `test_collection_home_loads` | Golden DB restored; collection screen renders with real data | Collection nav active; KPI bar populated; at least one table row |
| 6 | `test_collection_tile_view` | Switch to Tile view and back to Table | Tiles visible with overlay artist label; table restored on return |
| 7 | `test_record_detail_tile` | Click tile → overlay appears; click View → detail modal opens | Tile has `active` class; `#modal-detail` visible; title non-empty |
| 8 | `test_column_sort` | Click Artist column header to cycle sort | asc (▲) → desc (▼) → cleared; `sorted` class tracks state |
| 9 | `test_group_by_artist` | Enable Group by Artist and disable it | Artist group headers appear; disappear after second toggle |
| 10 | `test_format_filter_bar` | Click a format tag to filter the table | Visible rows all contain the selected tag |
| 11 | `test_search_bar_filters` | Type in the search bar to filter records | Non-matching search returns zero rows; clearing restores full list |
| 12 | `test_surprise_me` | Click Surprise Me; detail modal opens | `#modal-detail` visible |
| 13 | `test_record_detail_fields` | Open London Grammar — If You Wait; all fields populated; cover and carousel present | All detail rows non-empty; cover image and carousel arrows visible |
| 14 | `test_tracklist_with_headings` | Open Raye — This Music May Contain Hope; tracklist tab; track rows and heading rows present | Tracklist table visible; both track and heading row types present |
| 15 | `test_record_modal_navigation` | Open Raye; click next arrow; modal updates to Fleetwood Mac — Rumours | `#detail-modal-title` updates to Fleetwood Mac |
| 16 | `test_cover_image_lightbox` | Open Raye; click cover image; lightbox opens with correct src | `#lightbox` visible; `#lightbox-img` src contains `/images/` |
| 17 | `test_sync_metadata` | Open Raye edit form; fetch button says "Sync Metadata"; click it; preview card appears | `#discogs-preview` visible and contains "Raye" |
| 18 | `test_sync_custom_fields` | Open Raye edit form; click Sync Custom Fields; diff modal opens | `#modal-discogs-sync` visible; preview content contains "Raye" |
| 19 | `test_edit_record_fields` | Edit all 9 purchase/condition fields on Raye; save; reopen detail; verify all 9 values | All 9 detail values match the saved inputs |
| 20 | `test_use_as_cover` | Open Raye; carousel to image 2; Use as Cover; toast confirms; button disabled | "Cover updated" toast; Use as Cover disabled on new cover |
| 21 | `test_add_record` | Open add modal; enter Discogs ID; fetch populates fields and preview; save; row count increments | `#f-artist` non-empty; `#discogs-preview` visible; table row count +1 |
| 22 | `test_delete_record` | Open Rick Astley — Never Gonna Give You Up via edit form; delete via confirm dialog; row count decrements | "Record deleted" toast; table row count -1 |

**Status: tests 5–22 passing ✅ · test 7 pending first run**

---

### Remaining to port — `layer2/test_smoke.py` (backlog)

These tests are yet to be written as part of the sequential journey.

| # | Test | Purpose | Expected outcome |
|---|------|---------|-----------------|
| 21 | `test_delete_record` | Deleting a record removes it from the table | Row count decrements by one |
| 22 | `test_record_detail_tile` | Tile: tap → overlay; tap again → detail modal | Modal visible with a non-empty title |
| 23 | `test_wishlist_section_loads` | Switching to the Wishlist section works | Wishlist content visible; format bar hidden; Show Fulfilled toggle present |
| 24 | `test_wishlist_search_modal` | Search bar opens the master release search modal | Modal appears; results load after typing a query |
| 25 | `test_add_to_wishlist` | Adding a search result to the wishlist works | Item appears in the wishlist table |
| 26 | `test_wishlist_tile_view` | Wishlist tile view renders covers | Tiles visible in wishlist |
| 27 | `test_wishlist_detail_modal` | Clicking a wishlist item opens its detail modal | Modal visible with editable notes field |
| 28 | `test_wishlist_save_notes` | Notes saved in the wishlist detail modal persist after close and reopen | Reopened modal shows the previously entered text |
| 29 | `test_mark_wishlist_fulfilled` | Marking an item fulfilled hides it from the list | Row count decrements; item gone from default view |
| 30 | `test_wishlist_show_fulfilled_toggle` | Show Fulfilled toggle reveals fulfilled items | Row count returns to pre-fulfilment value |
| 31 | `test_delete_wishlist_item` | Deleting a wishlist item removes it permanently | Row count decrements after delete |
| 32 | `test_settings_modal_open_close` | Settings modal opens and closes cleanly | Modal appears on gear click; disappears on Close |
| 33 | `test_settings_currency_change` | Changing the currency symbol takes effect | KPI cost displays the new symbol after save |
| 34 | `test_settings_include_pp` | Include P&P toggle changes the Collection Cost KPI | Cost KPI value differs after toggling on |
| 35 | `test_settings_show_valuations` | Show Valuations toggle hides and restores the Collection Value KPI | KPI hidden after toggle off; restored after toggle on |
| 36 | `test_settings_hide_format_tags` | Hide format tags toggle saves without error | Album tag visible after toggle off; hidden after toggle on |
| 37 | `test_export_csv_download` | Export CSV button triggers a file download | A `.csv` file download begins |
| 38 | `test_export_db_download` | Export Database button triggers a file download | A `.zip` file download begins |
| 39 | `test_export_images_download` | Export Images button triggers a file download | A `.zip` file download begins |
| 40 | `test_export_all_download` | Export All button triggers a file download | A `.zip` file download begins |
| 41 | `test_import_csv_opens_diff_modal` | Uploading a CSV file opens the sync diff modal | Diff modal becomes visible |
| 42 | `test_import_csv_apply_sync` | Uploading a CSV and clicking Apply Sync applies changes | Sync modal closes after apply |
| 43 | `test_collection_sync_preview` | Sync Collection in settings loads the preview modal | Diff modal and preview content visible |
| 44 | `test_danger_zone_delete_all` | Delete All Records wipes the collection | Empty collection state shown after confirm |
| 45 | `test_empty_collection_restore_button` | Blank DB shows the empty state with a restore button | "Your collection is empty" and restore button visible |
| 46 | `test_danger_zone_factory_reset` | Factory Reset wipes records and restores default settings | Empty state shown; cost KPI shows default £ symbol |
| 47 | `test_danger_zone_clear_images` | Clear Image Cache deletes cached covers | Toast confirms deletion count |
| 48 | `test_danger_zone_change_access_key` | Changing the access key via Danger Zone takes effect | Toast confirms update; app loads with new key injected |
| 49 | `test_danger_zone_import_db` | Import DB via Danger Zone replaces the database | Page reloads to empty collection state after importing blank DB |
| 50 | `test_auth_screen` | Setting an API key forces the auth screen on reload | Auth screen visible; entering the correct key loads the app |

---

### Old suite reference (101–145) — delete entries as ported above

| Old # | Test | Purpose | Expected outcome |
|-------|------|---------|-----------------|
| 115 | `test_wishlist_section_loads` | Switching to the Wishlist section works | Wishlist content visible; format bar hidden; Show Fulfilled toggle present |
| 116 | `test_wishlist_search_modal` | Search bar opens the master release search modal | Modal appears; results load after typing a query |
| 117 | `test_add_to_wishlist` | Adding a search result to the wishlist works | Item appears in the wishlist table |
| 118 | `test_wishlist_tile_view` | Wishlist tile view renders covers | Tiles visible in wishlist |
| 119 | `test_wishlist_detail_modal` | Clicking a wishlist item opens its detail modal | Modal visible with editable notes field |
| 120 | `test_mark_wishlist_fulfilled` | Marking an item fulfilled hides it from the list | Row count decrements; item gone from default view |
| 121 | `test_delete_wishlist_item` | Deleting a wishlist item removes it permanently | Row count decrements after delete |
| 122 | `test_settings_modal_open_close` | Settings modal opens and closes cleanly | Modal appears on gear click; disappears on Close |
| 123 | `test_settings_currency_change` | Changing the currency symbol takes effect immediately | KPI cost displays the new symbol after save |
| 124 | `test_export_csv_download` | Export CSV button triggers a file download | A `.csv` file download begins |
| 125 | `test_export_db_download` | Export Database button triggers a file download | A `.zip` file download begins |
| 126 | `test_import_csv_opens_diff_modal` | Uploading a CSV file opens the sync diff modal | Diff modal becomes visible |
| 127 | `test_collection_sync_preview` | Sync Collection in settings loads the preview modal | Diff modal and preview content visible |
| 128 | `test_auth_screen` | Setting an API key forces the auth screen on reload | Auth screen visible; entering the correct key loads the app |
| 132 | `test_wishlist_show_fulfilled_toggle` | Show Fulfilled toggle reveals items hidden after marking fulfilled | After toggling on, row count returns to the value before fulfilment |
| 133 | `test_wishlist_save_notes` | Notes saved in the wishlist detail modal persist after close and reopen | Reopened modal shows the previously entered text |
| 134 | `test_export_images_download` | Export Images button triggers a file download | A `.zip` file download begins |
| 135 | `test_export_all_download` | Export All button triggers a file download | A `.zip` file download begins |
| 136 | `test_import_csv_apply_sync` | Uploading a CSV and clicking Apply Sync applies changes to SN | Sync modal closes after apply |
| 137 | `test_settings_include_pp` | Include P&P toggle changes the Collection Cost KPI | Cost KPI value differs after toggling on (skips if no records with p&p) |
| 138 | `test_settings_show_valuations` | Show Valuations toggle hides and restores the Collection Value KPI | KPI stat hidden after toggle off; restored after toggle on |
| 139 | `test_settings_hide_format_tags` | Hide format tags toggle saves without error | Album tag visible after toggle off; hidden after toggle on |
| 140 | `test_danger_zone_delete_all` | Delete All Records wipes the collection | Empty collection state shown after confirm |
| 141 | `test_empty_collection_restore_button` | Blank DB shows the empty state with a restore-from-backup button | "Your collection is empty" text and restore button visible |
| 142 | `test_danger_zone_factory_reset` | Factory Reset wipes records and restores default settings | Empty state shown; cost KPI shows default £ symbol |
| 143 | `test_danger_zone_clear_images` | Clear Image Cache deletes cached covers | Toast confirms deletion count |
| 144 | `test_danger_zone_change_access_key` | Changing the access key via Danger Zone takes effect | Toast confirms update; app loads with new key injected |
| 145 | `test_danger_zone_import_db` | Import DB via Danger Zone replaces the database | Page reloads to empty collection state after importing blank DB |
