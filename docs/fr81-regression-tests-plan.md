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
    golden.sql             # golden DB (SQL text dump) — gitignored (personal data)
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
prepare-backup-for-test.sh # helper: patches live backup zip with test credentials
run-first-run.sh           # helper: runs the first-run test suite with --full-reset
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

**`tests/fixtures/golden.sql`** — the primary Layer 2 start state (SQL text dump, not a SQLite binary). See DB States section.

**`tests/fixtures/edge/*.sql`** — edge case DBs created as needed.

---

## DB States

Layer 2 tests start from a known DB state. This catches bugs that a blank DB never would — KPI calculations with accumulated data, sort behaviour with realistic record counts, etc.

### Golden DB (`tests/fixtures/golden.sql`)

The default start state for tests 101–145. A realistic collection exported from the live app, with live credentials replaced by test credentials. Stored as a raw SQL text dump (not a zip) so `_load_db()` in conftest can re-wrap it for the import API.

**Creating / updating:**
1. Take a full backup from the live app: Settings → Export All
2. Run `./tests/prepare-backup-for-test.sh tests/fixtures/sleevenotes_backup.zip`
   - This replaces `discogs_username`, `discogs_token`, and `api_key` with test values from `.env.test`
   - Outputs `tests/fixtures/sleevenotes_backup-test-ready.zip`
3. Import the test-ready zip into the local container via the UI
4. Export just the DB: `GET /api/export/db` (or use the script below)
5. Extract and save: `./tests/prepare-backup-for-test.sh` handles this, or run manually:

```bash
/home/kieran/.venvs/sleevenotes-tests/bin/python - <<'EOF'
import httpx, zipfile, io
from pathlib import Path
r = httpx.get("http://localhost:2026/api/export/db", headers={"X-API-Key": "NeverGonnaGiveYouUp"}, timeout=30)
r.raise_for_status()
with zipfile.ZipFile(io.BytesIO(r.content)) as z:
    sql_name = next(n for n in z.namelist() if n.endswith(".sql"))
    sql = z.read(sql_name)
Path("tests/fixtures/golden.sql").write_bytes(sql)
EOF
```

**Loading:** `_load_db()` in conftest re-wraps the SQL in a zip and POSTs to `/api/import/db`. Then `_configure_credentials()` PUTs test credentials from `.env.test`.

### Blank DB (`tests/fixtures/blank.sql`)

Empty but fully initialised (schema only, settings at defaults, no records). Committed to the repo — no personal data. Used by first-run tests and danger zone tests that require a pristine state.

---

## Test Numbering

| Range | Suite | Trigger |
|-------|-------|---------|
| 1–99 | First-run setup flow | `./tests/run-first-run.sh` (requires `--full-reset`) |
| 101–145 | Golden DB smoke suite | `pytest tests/layer2/ -m smoke` |

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
- **Per-test `page` fixture**: fresh tab per test within the shared context.
- **`restore_golden_db` autouse fixture**: reloads `golden.sql` into the container before each non-first_run test. Ensures each test starts clean without clearing browser state.
- **`maybe_full_reset`**: nukes and rebuilds the container with `compose.yml + compose.override.yml` (local build + `SN_DEV=true`). Requires interactive YES confirmation.
- **`require_full_reset_for_first_run`**: auto-skips first_run tests if `--full-reset` was not passed.

### Modal assertions

SleeveNotes modals use `opacity: 0 / pointer-events: none` for closed state — **not** `display: none`. Therefore:
- `to_be_hidden()` / `to_be_visible()` **does not work** for open/closed modal state
- Use `not_to_have_class(re.compile(r"\bopen\b"))` to assert a modal is closed
- `to_be_visible()` works fine for asserting content *inside* an open modal

### Running first-run tests

```bash
./tests/run-first-run.sh
```

Runs tests 1–4 with `--full-reset --headed --slowmo=1500`. Destroys and rebuilds the container from the current local branch. Requires interactive YES confirmation.

### Running the golden DB suite

```bash
/home/kieran/.venvs/sleevenotes-tests/bin/python -m pytest tests/layer2/ -m smoke -v
```

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

### Golden DB suite (101–145)

| # | Area | Test description |
|---|------|-----------------|
| 101 | App load | Navigate `/`; KPI bar, toolbar, main content visible |
| 102 | Add record | Open add modal; enter Discogs ID; fetch populates fields; save; record appears |
| 103 | Collection table | Golden DB has at least one record visible in table |
| 104 | Collection tiles | Switch to Tile view; tile renders with artist label |
| 105 | Column sort | Click Artist header; asc → desc → cleared |
| 106 | Group by artist | Enable Group by Artist; artist heading rows appear |
| 107 | Format filter bar | Click a format tag; table filters to matching records |
| 108 | Search bar | Type partial artist name; table filters live |
| 109 | Record detail modal | Tile: tap → overlay; tap again → detail modal with metadata |
| 110 | Tracklist tab | In detail modal, click Tracklist tab; track rows render |
| 111 | Edit record | Edit Notes; Save; reopen edit form; value retained |
| 112 | Delete record | Delete a record; row removed; count decrements |
| 113 | KPI — total | Total Records KPI visible and non-zero |
| 114 | KPI — cost | Collection Cost KPI shows currency symbol and value > 0 |
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
| 129 | KPI — value | Collection Value KPI visible with a digit |
| 130 | Image carousel | Record with >1 image shows carousel arrows |
| 131 | Use as Cover | Navigate carousel; click Use as Cover; toast confirms |
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

**Status: not yet run against current golden DB — next step.**

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
4. ~~Golden DB curation~~ ✅ — `tests/fixtures/golden.sql` saved from live
5. **Run tests 101–145 against golden DB** — fix any selector mismatches or assertion gaps
6. **Add SleeveNotes to NoveriaBackup.sh** — pause container, tar `/data` volume, unpause; currently not backed up
7. **Merge `feat/regression-tests` to `main`** once 101–145 are passing
8. **Regression check on `feat/wishlist-versions-v2`** — checkout branch; run Layer 1; all should still be green
9. **Add FR73-specific tests** — `test_wishlist_versions.py`, `test_wantlist.py`, `test_smoke_versions.py`
