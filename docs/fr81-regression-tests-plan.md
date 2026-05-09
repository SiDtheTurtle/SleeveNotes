# FR #81 — Automated Regression Test Suite

## Context

SleeveNotes has no test infrastructure. FR73 required an extensive manual test checklist (40 cases across 14 sections). FR #81 automates this to give a repeatable safety net for every future release.

Two-layer approach:
- **Layer 1** — pytest + httpx API tests. Fast, no Docker. Catches broken endpoints and business logic cheaply.
- **Layer 2** — Playwright smoke tests. Runs against the local dev container on port 2026. Catches what a human would notice.

**Branch workflow:**
1. Implement baseline tests on `feat/regression-tests` → merge to `main`
2. Run on `main` → establish green baseline
3. Switch to `feat/wishlist-versions-v2` → run baseline (regression check — all should still pass)
4. Add FR73-specific tests on the feature branch

---

## File Structure

```
tests/
  conftest.py              # shared Layer 1 fixtures
  requirements-test.txt    # test dependencies
  .env.test                # local secrets — gitignored
  .env.test.example        # committed template with blank values
  fixtures/
    golden.zip             # golden DB backup (SQL + images) — gitignored (personal data)
    blank.sql              # empty initialised DB (SQL text dump) — committed (no personal data)
    edge/                  # edge case DBs — gitignored, created as needed
  layer1/
    __init__.py
    test_health_auth.py
    test_records.py
    test_settings.py
    test_wishlist.py
    test_collection_sync.py
    test_import_export.py
    test_admin.py
  layer2/
    __init__.py
    conftest.py            # loads .env.test, manages golden DB, browser context
    test_smoke.py
pytest.ini                 # at project root; asyncio_mode, smoke + first_run markers, default exclusion
run-first-run.sh           # runs the full sequential test suite; accepts optional start number
```

FR73 additions (on `feat/wishlist-versions-v2` only, added in a later session):
```
  layer1/
    test_wishlist_versions.py
    test_wantlist.py
  layer2/
    test_smoke_versions.py
```

---

## Architecture: No Separate Test Container

**The test suite runs against the local dev container on port 2026** — the same container used for development. There is no separate `compose.test.yml`.

The `--full-reset` flag in `run-first-run.sh` tears down and rebuilds this container using both `compose.yml` and `compose.override.yml` (which forces a local build and sets `SN_DEV=true`). This means:
- Tests always run against the current local branch
- The dev banner is present (allowing tests to assert dev-only UI state)
- No port conflicts — there is only one container

**Implication:** Running `--full-reset` destroys the working dev container. The interactive YES prompt guards against accidental destruction.

---

## Gitignored Local Files

**`tests/.env.test`** — credentials for Layer 2:
```
DISCOGS_TEST_USERNAME=sleevenotes_test
DISCOGS_TEST_TOKEN=<test account API token>
SN_TEST_API_KEY=<SleeveNotes access key — set during first-run tests>
SN_TEST_ADD_RELEASE_ID=[r35207593]
```

**`tests/fixtures/golden.zip`** — the primary Layer 2 start state (SQL + images combined backup). See DB States section.

**`tests/fixtures/edge/*.sql`** — edge case DBs created as needed.

---

## DB States

Layer 2 tests start from a known DB state. This catches bugs that a blank DB never would — KPI calculations with accumulated data, sort behaviour with realistic record counts, etc.

### Golden DB (`tests/fixtures/golden.zip`)

The start state for test 5 onwards. A realistic collection exported from the live app via Settings → Export All, with test credentials baked in (`api_key`, `discogs_username`, `discogs_token` must match `.env.test` values). Stored as a combined zip (SQL + images) so cover thumbnails are present after restore.

**Creating / updating:**
1. Configure the local container with test credentials (`SN_TEST_API_KEY`, `DISCOGS_TEST_USERNAME`, `DISCOGS_TEST_TOKEN` from `.env.test`)
2. Settings → Export All → save as `tests/fixtures/golden.zip`

**Loading:** `_restore_golden()` in conftest POSTs `golden.zip` to `/api/import/all`, restoring both DB and images in one step. No separate credential injection needed — the zip contains the correct credentials already.

**Key requirement:** the `api_key` stored in `golden.zip` must equal `SN_TEST_API_KEY` in `.env.test`, otherwise the browser's injected key will be rejected after restore.

### Blank DB (`tests/fixtures/blank.sql`)

Empty but fully initialised (schema only, settings at defaults, no records). Committed to the repo — no personal data. Used by first-run tests and danger zone tests that require a pristine state.

---

## Test Numbering

All Layer 2 tests form a single sequential journey in `test_smoke.py`. Tests run in order; DB state accumulates across tests within a session.

| Range | Suite | Notes |
|-------|-------|-------|
| 1–4 | First-run setup flow | Require `--full-reset`; skipped automatically otherwise |
| 5+ | Collection & feature tests | Test 5 restores golden DB via `restore_golden_db` fixture; subsequent tests build on that state |

### Running

```bash
./tests/run-first-run.sh        # full run from test 1 (--full-reset)
./tests/run-first-run.sh 5      # resume from test 5 (--inject-api-key)
./tests/run-first-run.sh 3      # resume from test 3 (--inject-api-key)
```

`--inject-api-key`: injects `SN_TEST_API_KEY` into the browser's localStorage (via `page.add_init_script`) so the auth screen is bypassed when resuming mid-session. Does not touch the server DB.

**localStorage note:** `lsSet()` in the frontend stores values via `JSON.stringify`. The init script must therefore use `JSON.stringify` too: `localStorage.setItem('sn_apiKey', JSON.stringify(key))`.

---

## pytest.ini

Located at **project root** (not `tests/`).

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
markers =
    smoke: Playwright E2E smoke tests (require the dev container running on :2026)
    first_run: Tests that require a --full-reset blank container (no golden DB, no API key)
addopts = -m "not smoke"
```

---

## Layer 2 — Playwright Smoke Tests

### `tests/layer2/conftest.py` — key design decisions

- **Session-scoped `browser_context`**: localStorage persists across all tests within a run. This is intentional — accumulation exposes real bugs that a reset-per-test approach would hide.
- **Per-test `page` fixture**: fresh tab per test within the shared context. When `--inject-api-key` is set, adds an init script that pre-seeds `localStorage.sn_apiKey` (JSON-stringified) before the page's own JS runs.
- **`restore_golden_db` fixture**: non-autouse, function-scoped. Declares as a parameter only on tests that need a known-good state (currently test 5 only). Calls `_restore_golden()` which POSTs `golden.zip` to `/api/import/all`. No credential injection — credentials are baked into the zip.
- **`maybe_full_reset`**: nukes and rebuilds the container with `compose.yml + compose.override.yml` (local build + `SN_DEV=true`). Requires interactive YES confirmation. Also runs `docker volume rm sleevenotes_data` explicitly, since `compose down -v` does not remove volumes with an explicit `name:` in the compose file.
- **`configure_test_container`**: session-scoped autouse. With `--full-reset`: no-op (container must stay blank for tests 1–4). With `--inject-api-key`: no-op (browser handles key injection; DB already in correct state). Otherwise: restores golden DB at session start.
- **`require_full_reset_for_first_run`**: auto-skips first_run tests if `--full-reset` was not passed.

### Modal assertions

SleeveNotes modals use `opacity: 0 / pointer-events: none` for closed state — **not** `display: none`. Therefore:
- `to_be_hidden()` / `to_be_visible()` **does not work** for open/closed modal state
- Use `not_to_have_class(re.compile(r"\bopen\b"))` to assert a modal is closed
- `to_be_visible()` works fine for asserting content *inside* an open modal

### Running

```bash
./tests/run-first-run.sh        # full run from test 1 (--full-reset)
./tests/run-first-run.sh 5      # resume from test 5 (--inject-api-key)
```

Full run destroys and rebuilds the container. Requires interactive YES confirmation.

---

## Layer 2 — Test Index

### First-run suite (1–4)

| # | Name | What it tests |
|---|------|--------------|
| 1 | `test_first_run_auth_prompt` | Blank container shows "Choose an access key" setup screen |
| 2 | `test_first_run_set_api_key` | Set API key via UI; app loads with empty collection |
| 3 | `test_first_run_discogs_credentials` | Enter Discogs username + token; save; field mapping section loads |
| 4 | `test_first_run_field_mappings` | Set all 9 field mappings; save; close; reopen; verify persistence |

**Status: all 4 passing ✅**

### Collection & feature suite (5+)

| # | Area | Test description | Status |
|---|------|-----------------|--------|
| 5 | Collection home | Golden DB restored; KPI bar populated; at least one table row | ✅ |
| 6 | Tile view | Switch to Tile; tiles visible with overlay artist; switch back to Table | ✅ |
| 7 | Tile detail | Click tile → overlay; click View → detail modal opens | ✅ |
| 8 | Column sort | Click Artist header; asc (▲) → desc (▼) → cleared; `sorted` class tracks state | ✅ |
| 9 | Group by artist | Enable Group by Artist; group-header rows appear; disable; rows gone | ✅ |
| 10 | Format filter bar | Click a format tag; visible rows all contain the tag | ✅ |
| 11 | Search bar | Type partial artist name; table filters live; clear restores full list | ✅ |
| 12 | Surprise Me | Click Surprise Me; detail modal opens | ✅ |
| 13 | Record detail fields | Open London Grammar — If You Wait; all fields populated; cover and carousel present | ✅ |
| 14 | Tracklist with headings | Open Raye — This Music May Contain Hope; switch to Tracklist tab; track rows and heading rows present | ✅ |
| 15 | Record modal navigation | Open Raye; click next arrow; modal updates to Fleetwood Mac — Rumours | ✅ |
| 16 | Cover image lightbox | Open Raye; click cover image; lightbox opens with correct src | ✅ |
| 17 | Sync Metadata | Open Raye edit form; assert fetch-btn says "Sync Metadata"; click it; discogs-preview card appears with artist | ✅ |
| 18 | Sync Custom Fields | Open Raye edit form; click Sync Custom Fields; diff modal opens and preview content loads | ✅ |
| 19 | Edit record fields | Edit all 9 purchase/condition fields on Raye; save; reopen detail; assert all 9 values persisted | ✅ |
| 20 | Use as Cover | Open Raye; carousel arrow to image 2; Use as Cover; toast confirms; button disabled for new cover | ✅ |
| 21 | Add record | Open add modal; enter Discogs ID (Rick Astley); fetch populates fields + preview; save; row count +1 | ✅ |
| 22 | Delete record | Open Rick Astley via edit form; delete via confirm dialog; row count -1 | ✅ |

**Remaining to port from old suite (backlog):**

| Old # | Area | Test description |
|-------|------|-----------------|
| 115 | Wishlist section | Click Wishlist nav; wishlist table renders; format bar hidden |
| 116 | Wishlist search | Open search modal; type query; results appear |
| 117 | Add to wishlist | Add a result; item appears in wishlist table |
| 118 | Wishlist tiles | Switch to Tile view in wishlist; cover tile renders |
| 119 | Wishlist detail | Click item; detail modal opens; notes field editable |
| 120 | Mark fulfilled | Check fulfilled; Save; item hidden from default view |
| 121 | Delete wishlist item | Open detail; Delete; item removed |
| 122 | Settings — open/close | Gear icon opens modal; Close dismisses |
| 123 | Settings — currency | Change to `$`; Save; KPI cost shows `$` |
| 124 | Export CSV | Export CSV; download triggers |
| 125 | Export DB | Export Database; zip download triggers |
| 126 | Import CSV | Upload valid Discogs CSV; sync diff modal opens |
| 127 | Collection sync | Sync Collection; preview modal loads with content |
| 128 | Auth screen | Set API key; reload; auth screen appears; enter key; app loads |
| 132 | Show Fulfilled toggle | Mark fulfilled; toggle Show Fulfilled; item reappears |
| 133 | Wishlist notes persist | Edit notes; Save; reopen; notes retained |
| 134 | Export Images | Export Images; zip download triggers |
| 135 | Export All | Export All; zip download triggers |
| 136 | Import CSV — apply | Upload CSV; apply sync; modal closes |
| 137 | Settings — Include P&P | Toggle on; Save; cost KPI changes |
| 138 | Settings — Show Valuations | Toggle off; KPI hidden. Toggle on; KPI visible |
| 139 | Settings — Hide format tags | Toggle off; Album tag visible. Toggle on; tag hidden |
| 140 | Danger Zone — Delete All | Confirm; empty collection state shown |
| 141 | Empty collection state | "Your collection is empty" and restore button visible |
| 142 | Danger Zone — Factory Reset | Confirm; empty state; cost KPI shows `£` |
| 143 | Danger Zone — Clear Images | Confirm; toast shows deletion count |
| 144 | Danger Zone — Change Key | Enter new key; save; app still loads |
| 145 | Danger Zone — Import DB | Upload blank.sql zip; page reloads to empty collection |

---

## Layer 1 — API Tests

**65 tests across 7 files — all passing. ✅**

All 32 API endpoints covered. See `tests/TEST_INDEX.md` for full reference.

---

## Dependencies

Install once:
```bash
/home/kieran/.venvs/sleevenotes-tests/bin/pip install -r tests/requirements-test.txt
/home/kieran/.venvs/sleevenotes-tests/bin/playwright install chromium
```

Python venv: `/home/kieran/.venvs/sleevenotes-tests/`

---

## Next Steps

1. ~~Layer 1 API tests (65 tests, all endpoints)~~ ✅
2. ~~Layer 2 efficacy review and fixes~~ ✅
3. ~~First-run test suite (tests 1–4)~~ ✅ — all passing
4. ~~Golden DB curation~~ ✅ — `tests/fixtures/golden.zip` (SQL + images) exported from live
5. ~~Mid-session restart~~ ✅ — `--inject-api-key` seeds browser localStorage; `JSON.stringify` required to match `lsSet` encoding
6. ~~Fix test 8 ungroup assertion~~ ✅ — click `.toggle-track`, use `.group-header` selector
7. ~~Tests 9–22~~ ✅ — format filter, search, Surprise Me, detail fields, tracklist, navigation, lightbox, sync metadata, sync custom fields, edit fields, use as cover, tile detail, add record, delete record
8. **Port remaining backlog tests (115–145)** as sequential journey tests — audit selectors against HTML before writing
9. **Add SleeveNotes to NoveriaBackup.sh** — pause container, tar `/data` volume, unpause; currently not backed up
10. **Merge `feat/regression-tests` to `main`** once suite is stable
11. **Regression check on `feat/wishlist-versions-v2`** — checkout branch; run Layer 1; all should still be green
12. **Add FR73-specific tests** — `test_wishlist_versions.py`, `test_wantlist.py`, `test_smoke_versions.py`
