# FR #81 — Automated Regression Test Suite

## Context

SleeveNotes has no test infrastructure. FR73 required an extensive manual test checklist (40 cases across 14 sections). FR #81 automates this to give a repeatable safety net for every future release.

Two-layer approach:
- **Layer 1** — pytest + httpx API tests. Fast, no Docker. Catches broken endpoints and business logic cheaply.
- **Layer 2** — Playwright smoke tests. Runs against a dedicated test Docker container (port 2027). Catches what a human would notice.

**Branch workflow:**
1. Implement baseline tests on `main` branch
2. Run on `main` → establish green baseline
3. Switch to `feat/wishlist-versions-v2` → run baseline (regression check — all should still pass)
4. Add FR73-specific tests on the feature branch

---

## File Structure

```
tests/
  conftest.py              # shared Layer 1 fixtures
  pytest.ini               # asyncio_mode=auto, smoke marker, default exclusion
  requirements-test.txt    # test dependencies
  .env.test                # local secrets — gitignored
  fixtures/
    golden.db              # golden DB — gitignored (personal, backed up on NAS)
    blank.db              # empty initialised DB — committed (no personal data)
    edge/
      large_wishlist.db    # edge case DBs — gitignored, created as needed
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
    conftest.py            # loads .env.test, loads golden DB into test container
    test_smoke.py
compose.test.yml           # test Docker stack (port 2027, separate data volume)
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

## Gitignored Local Files

All of the following are added to `.gitignore`. None are secret, but they contain personal data or are environment-specific. The NAS backup covers them.

**`tests/.env.test`** — credentials for Layer 2:
```
DISCOGS_TEST_USERNAME=<test account username>
DISCOGS_TEST_TOKEN=<test account API token>
SN_TEST_API_KEY=<SleeveNotes access key on test container>
```
A `tests/.env.test.example` with blank values is committed as a template.

**`tests/fixtures/golden.db`** — the primary Layer 2 start state (see below).

**`tests/fixtures/edge/*.db`** — edge case DBs created as needed.

---

## DB States

Layer 2 tests start from a known DB state rather than building from scratch each run. This catches bugs that a blank DB never would — migration guards on existing columns, KPI calculations with accumulated data, sort behaviour with realistic record counts, etc.

### Golden DB (`tests/fixtures/golden.db`)

The default start state for almost all Layer 2 tests. A realistic "lived-in" DB curated manually using the test Discogs account: a spread of records with varied conditions, formats, prices, and dates; a few wishlist items; at least one fulfilled item. Created and maintained by the developer.

**Loading into the test container:** The Layer 2 session fixture POSTs `golden.db` to `POST /api/import/db` on `:2027` at the start of each run. This replaces whatever is in the test container's volume.

**Updating the golden DB:** Run the test container normally (`:2027`), make changes via the UI, then `GET /api/export/db` and unzip the `.sql` into `tests/fixtures/golden.db`. Commit the update to git is intentionally not possible — it lives on the NAS only.

### Blank DB (`tests/fixtures/blank.db`)

An empty but fully initialised DB (schema created, all settings at defaults, no records). Committed to the repo — contains no personal data. Used explicitly by tests that require a fresh-install state:
- First-run auth screen
- Empty collection placeholder
- Factory reset result
- `POST /api/admin/factory-reset` expected outcome

Generated once by calling `init_db()` against a blank file and committed.

### Edge Case DBs (`tests/fixtures/edge/`)

Created on demand for specific scenarios. Gitignored. Examples:
- `large_wishlist.db` — hundreds of wishlist items (pagination testing)
- `missing_covers.db` — records with no cached cover images

Each edge case DB is documented inline in the test that uses it, with notes on how to recreate it.

---

## Test Docker Stack — `compose.test.yml`

Separate stack so the live container on :2026 is never touched during testing.

```yaml
services:
  sleevenotes-test:
    build: .
    ports:
      - "2027:2026"
    volumes:
      - sleevenotes-test-data:/data
    environment:
      - DEV=true

volumes:
  sleevenotes-test-data:
```

Run before Layer 2: `docker compose -f compose.test.yml up --build -d`

Layer 2 `conftest.py` session fixture PUTs the test Discogs credentials and SN API key to `:2027/api/settings` on startup, and resets the DB via `/api/admin/factory-reset` between test modules to ensure clean state.

---

## Dependencies

**`tests/requirements-test.txt`**
```
pytest>=8.0
pytest-asyncio>=0.23
httpx>=0.27
pytest-mock>=3.12
playwright>=1.44
pytest-playwright>=0.5
python-dotenv>=1.0
```

Install: `pip install -r tests/requirements-test.txt && playwright install chromium`

---

## pytest.ini

```ini
[pytest]
asyncio_mode = auto
markers =
    smoke: Playwright E2E smoke tests (require compose.test.yml running on :2027)
addopts = -m "not smoke"
```

---

## Layer 1 — API Tests

### `tests/conftest.py` — shared fixtures

- **`client`** fixture: monkeypatches `app.DB_PATH` to `tmp_path / "test.db"`, resets `app._cached_api_key = None`, calls `app.init_db()`, yields `AsyncClient(transport=ASGITransport(app=app.app), base_url="http://test")`
- **`mock_discogs_get`** / **`mock_discogs_post`** fixtures: `mocker.patch("app.discogs_get")` / `mocker.patch("app.discogs_post")` returning configurable fixture dicts

### `test_health_auth.py`
- `GET /api/health` → 200, `{"status": "ok"}`
- `GET /api/auth/status` → `{"configured": false}` with no key set
- Protected endpoint → 401 when key set and `X-API-Key` header missing
- Protected endpoint → 200 with correct key

### `test_records.py`
- `GET /api/records` → `[]` on empty DB
- `POST /api/records` → 201, record in response body
- `GET /api/records` → returns the created record
- `PUT /api/records/{id}` → updates field, confirmed in subsequent GET
- `DELETE /api/records/{id}` → 200; record absent from `GET /api/records`
- Soft-deleted record has `deleted_at` set

### `test_settings.py`
- `GET /api/settings` → all SETTINGS_DEFAULTS keys present on fresh DB
- `GET /api/settings` → `api_key` absent from response
- `PUT /api/settings/currency` → updates value; confirmed in subsequent GET

### `test_wishlist.py`
- `GET /api/wishlist` → `[]` on empty DB
- `POST /api/wishlist` (mocked Discogs `/masters/{id}` response) → 201, item in response
- `GET /api/wishlist` → returns created item
- `POST /api/wishlist` same master_id → 409
- `PUT /api/wishlist/{id}` → updates notes and fulfilled
- `GET /api/wishlist` → fulfilled item excluded by default
- `GET /api/wishlist?show_fulfilled=true` → fulfilled item included
- `DELETE /api/wishlist/{id}` → item absent from list

### `test_collection_sync.py`
- `compute_diff` (called directly) with empty DB → all items in `new`
- `compute_diff` with matching `instance_id`, no field changes → item in `unchanged`
- `compute_diff` with changed `artist` → item in `changed` with correct `from`/`to`
- `POST /api/collection/sync` → records created, confirmed via `GET /api/records`
- Currency mismatch → diff entry has `currency_mismatch: true`

### `test_import_export.py`
- `GET /api/export` → 200, `text/csv`, correct headers present
- `GET /api/export` with seeded records → rows present
- `GET /api/export/db` → 200, `application/zip`, zip contains `.sql`
- `POST /api/import/csv` with minimal Discogs-format CSV → diff payload returned with `new` items

### `test_admin.py`
- `POST /api/admin/format` → `GET /api/records` returns `[]`; settings unchanged
- `POST /api/admin/factory-reset` → records deleted; settings reset to SETTINGS_DEFAULTS
- `POST /api/admin/clear-images` → 200

---

## Layer 2 — Playwright Smoke Tests

All marked `@pytest.mark.smoke`. Target `http://localhost:2027` (test container). A session-scoped fixture configures Discogs + SN credentials from `tests/.env.test` and resets the DB before each module.

### `tests/layer2/conftest.py`
- Load `tests/.env.test` via `python-dotenv`
- Session fixture: POST `golden.db` to `/api/import/db` on `:2027`; PUT `discogs_username`, `discogs_token`, `api_key` from `.env.test`
- Per-test autouse fixture: restores golden DB via `/api/import/db` before each test (ensures clean slate even if previous test left dirty state)
- Tests that require blank DB call a helper that POSTs `blank.db` instead, then restore golden after
- `page` fixture injects `X-API-Key` header for all requests

### `tests/layer2/test_smoke.py` — one test per functional area

| # | Area | Test description |
|---|------|-----------------|
| 1 | App load | Navigate `/`; KPI bar and collection table visible |
| 2 | Add record | Open add modal; enter Discogs ID; Fetch populates fields; Save; record in table |
| 3 | Collection table | Seeded record shows correct artist, title, year columns |
| 4 | Collection tiles | Switch to Tile view; cover tile renders with artist label |
| 5 | Column sort | Click Artist header; rows reorder; click again reverses; click again clears |
| 6 | Group by artist | Enable Group by Artist; artist heading rows appear |
| 7 | Format filter | Format tag bar visible; click a tag; table filters to matching records only |
| 8 | Search bar | Type partial artist name; table filters live |
| 9 | Record detail modal | Tile view: tap cover once (overlay), tap again → detail modal opens with metadata |
| 10 | Tracklist tab | In detail modal, click Tracklist tab; track rows render |
| 11 | Edit record | Click edit; change Notes field; Save; updated value visible in table row |
| 12 | Delete record | Click delete on row; confirm; row removed; total count decrements |
| 13 | KPI — total | Add a record; Total Records KPI increments |
| 14 | KPI — cost | Add record with price; Collection Cost KPI reflects it |
| 15 | Wishlist section | Click Wishlist nav; wishlist table renders; format bar hidden |
| 16 | Wishlist search | Click search bar / Enter; search modal opens; type query; results appear |
| 17 | Add to wishlist | Add result; item appears in wishlist table with artist, title, year |
| 18 | Wishlist tiles | Switch to Tile view in wishlist; cover tile renders |
| 19 | Wishlist detail | Click wishlist item; detail modal opens; notes field editable |
| 20 | Mark fulfilled | Check fulfilled; Save; item hidden; Show Fulfilled toggle reveals it |
| 21 | Delete wishlist item | Open detail; Delete; item removed from list |
| 22 | Settings — open/close | Gear icon opens modal; Close dismisses without change |
| 23 | Settings — currency | Change currency to `$`; Save; KPI cost shows `$` symbol |
| 24 | Export CSV | Click Export CSV; download triggers (check `download` event fires) |
| 25 | Export DB | Click Export Database; zip download triggers |
| 26 | Import CSV | Upload a minimal valid Discogs CSV; sync diff modal opens |
| 27 | Collection sync | Settings → Sync Collection; preview modal loads with diff sections |
| 28 | Auth screen | Set an API key; reload page; auth screen appears; enter key; app loads |

---

## Critical Files

| File | Purpose |
|------|---------|
| `app.py` | Source under test — no changes needed |
| `tests/conftest.py` | Layer 1 fixture: patches `app.DB_PATH`, calls `init_db()`, yields `AsyncClient` |
| `tests/pytest.ini` | asyncio_mode, smoke marker, default `-m "not smoke"` |
| `tests/requirements-test.txt` | All test dependencies |
| `tests/.env.test` | Credentials — gitignored |
| `tests/.env.test.example` | Committed template with blank values |
| `tests/fixtures/golden.db` | Golden DB — gitignored, on NAS backup |
| `tests/fixtures/blank.db` | Empty initialised DB — committed (no personal data) |
| `tests/fixtures/edge/` | Edge case DBs — gitignored, created as needed |
| `compose.test.yml` | Test Docker stack on port 2027 |
| `tests/layer1/*.py` | API regression tests |
| `tests/layer2/conftest.py` | Loads secrets, loads golden DB into test container |
| `tests/layer2/test_smoke.py` | 28 Playwright UI tests |

---

## Running Tests

```bash
# Layer 1 only (fast, no Docker needed)
pytest tests/layer1/ -v

# Start test container (for Layer 2)
docker compose -f compose.test.yml up --build -d

# Layer 2
pytest tests/layer2/ -m smoke -v

# Both layers
pytest tests/ -m smoke -v

# FR73-specific (on feature branch, added later)
pytest tests/layer1/test_wishlist_versions.py tests/layer1/test_wantlist.py -v
pytest tests/layer2/test_smoke_versions.py -m smoke -v
```

---

## Verification

1. Checkout `main`
2. `pip install -r tests/requirements-test.txt && playwright install chromium`
3. `pytest tests/layer1/ -v` → all green (baseline) ✅ **Done**
4. `docker compose -f compose.test.yml up --build -d`
5. Populate `tests/.env.test` with test Discogs credentials
6. `pytest tests/layer2/ -m smoke -v` → all green
7. Checkout `feat/wishlist-versions-v2`
8. `pytest tests/layer1/ -v` → still all green (regression confirmed)
9. Add FR73 test files; run to validate feature branch

---

## Next Steps

1. **Review `tests/TEST_INDEX.md` for completeness** — confirm all meaningful behaviours are covered; add any missing test cases to the relevant Layer 1 file or note them as future Layer 2 additions
2. **Set up test Discogs account** — create a throwaway Discogs account; populate `tests/.env.test` with its username and token
3. **Start test container and curate golden DB** — `docker compose -f compose.test.yml up --build -d`; use the UI at `:2027` to add a realistic spread of records and wishlist items using the test account; export via `/api/export/db` and save to `tests/fixtures/golden.db`
4. **Run Layer 2 smoke tests** — `pytest tests/layer2/ -m smoke -v`; fix any selector mismatches against the live UI
5. **Run Layer 1 baseline against `feat/wishlist-versions-v2`** — checkout the FR73 branch; `pytest tests/layer1/ -v` should still be all green (regression check)
6. **Add FR73-specific tests** — `tests/layer1/test_wishlist_versions.py`, `tests/layer1/test_wantlist.py`, `tests/layer2/test_smoke_versions.py`
7. **Merge and release** — once all tests pass on both branches, merge `feat/regression-tests` to `main`; the workflow then repeats from step 5 for FR73
