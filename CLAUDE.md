# SleeveNotes

A personal vinyl record collection manager. Single-page app backed by a FastAPI/SQLite server, containerised with Docker.

## Stack

- **Backend:** Python 3.12, FastAPI, SQLite, httpx
- **Frontend:** Vanilla JS SPA (`static/index.html`) — no build step
- **Container:** Docker Compose, port 2026, persistent `/data` volume
- **Discogs API:** Token stored in the `settings` DB table (set via Settings modal)

## Project Structure

```
app.py              # FastAPI backend — all routes, DB, helpers
static/index.html   # Entire frontend — HTML, CSS, JS in one file
Dockerfile
compose.yml
compose.override.yml  # Forces local build (overrides registry image for dev)
```

Runtime data (not in repo):
```
/data/sleevenotes.db    # SQLite database
/data/images/           # Cached Discogs cover images
```

## Running Locally

```bash
docker compose up --build
# App available at http://localhost:2026
```

To reset the database:
```bash
docker exec sleevenotes rm /data/sleevenotes.db
# init_db() recreates the schema on next request
```

## Database

### `records` table

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `discogs_id` | TEXT | Format: `r12345678` |
| `instance_id` | TEXT | Discogs collection instance ID |
| `folder_id` | INTEGER | Discogs collection folder |
| `cat_no` | TEXT | Catalog number |
| `artist` | TEXT | Comma-separated if multiple |
| `title` | TEXT | |
| `label` | TEXT | |
| `year` | INTEGER | Release year |
| `format` | TEXT | e.g. "Vinyl, LP, Album" |
| `cover_file` | TEXT | Cached image filename in `/data/images/` |
| `is_new` | INTEGER | NULL = unknown, 0 = Pre-Owned, 1 = New |
| `curr_cond` | TEXT | S/M/NM/VG+/VG/G+/G/F/P — media condition |
| `sleeve_cond` | TEXT | Same scale — sleeve condition |
| `retailer` | TEXT | |
| `order_ref` | TEXT | |
| `purchase_date` | TEXT | ISO 8601 (YYYY-MM-DD) |
| `price` | REAL | Item cost (GBP); 0 means not entered |
| `pp` | REAL | Postage & packaging (GBP); 0 means not entered |
| `notes` | TEXT | |
| `valuation` | REAL | Discogs lowest listing price; 0 means not fetched |
| `created_at` | TEXT | Auto timestamp |
| `deleted_at` | TEXT | Soft-delete timestamp; NULL = active |

### `settings` table

| Key | Default | Notes |
|---|---|---|
| `clean_artists` | `true` | Strip Discogs disambiguation numbers from display |
| `include_pp` | `false` | Include P&P in Collection Cost KPI |
| `hide_obvious_formats` | `true` | Global on/off for format tag hiding |
| `hidden_format_tags` | `Album, LP, Stereo, Vinyl` | Comma-separated tags to hide from filter bar |
| `discogs_username` | `` | Required for collection sync |
| `discogs_token` | `` | Discogs API token (stored server-side, never sent to frontend) |
| `discogs_field_mappings` | `{}` | JSON: `{field_id: db_col}` mapping custom Discogs fields → SN columns |

`SETTINGS_DEFAULTS` in `app.py` is the single source of truth for defaults — used by both `init_db()` (INSERT OR IGNORE) and `POST /api/admin/factory-reset` (INSERT OR REPLACE).

### `images` table
Per-release image cache: `discogs_id`, `filename`, `seq`, `is_cover`.

### `tracklist` table
Per-release track data: `discogs_id`, `position`, `title`, `duration`, `type`, `seq`.

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/records` | List records (excludes soft-deleted) |
| POST | `/api/records` | Create record |
| PUT | `/api/records/{id}` | Update record |
| DELETE | `/api/records/{id}` | Soft-delete record |
| GET | `/api/discogs/{release_id}` | Fetch metadata + valuation from Discogs |
| POST | `/api/records/{id}/refresh` | Re-fetch Discogs data for existing record |
| GET | `/api/records/{id}/tracklist` | Get cached tracklist |
| GET | `/api/records/{id}/images` | Get cached images |
| POST | `/api/records/{id}/set-cover` | Set cover image |
| GET | `/api/collection/fields` | Fetch Discogs custom field definitions |
| GET | `/api/collection/preview` | Fetch full Discogs collection and return diff vs SN |
| POST | `/api/collection/sync` | Apply a sync payload (to SN and/or Discogs) |
| POST | `/api/import/csv` | Upload Discogs-format CSV → returns diff preview |
| GET | `/api/export` | Download CSV (all DB fields) |
| GET | `/api/settings` | Get all settings |
| PUT | `/api/settings/{key}` | Update a setting |
| POST | `/api/admin/format` | Delete all records (settings preserved) |
| POST | `/api/admin/factory-reset` | Delete all records + restore all settings to defaults |
| POST | `/api/admin/clear-images` | Delete all cached cover images from disk |

### Discogs rate limiter
All outbound Discogs API calls go through `discogs_get()` / `discogs_post()` wrappers that enforce a 55 req/min sliding-window limit (buffer under Discogs' 60/min). The limiter is process-wide — no manual sleep/batch logic anywhere else. On a 429 response, it waits 60 s and retries once. Image CDN calls (`i.discogs.com`) bypass the limiter — they are not API calls.

### Discogs fetch (`/api/discogs/{id}`)
- Accepts `r12345678` or `12345678`
- Makes 2 concurrent Discogs calls: `/releases/{id}` + `/marketplace/stats/{id}`
- Returns artist, title, label, cat_no, year, format, cover_file, valuation
- Downloads and caches all images (up to 8) to `/data/images/`; populates `tracklist` table

### Record refresh (`/api/records/{id}/refresh`)
- Updates Discogs-sourced fields only: artist, title, label, cat_no, year, format, cover_file, valuation, tracklist, images
- Preserves all user-entered fields

### Collection sync (`/api/collection/sync`)
- Accepts `{to_sleevenotes: [...], to_discogs: [...]}` payload
- New SN records trigger a background `_refresh_new_records` task (images + tracklist + valuation)
- Returns `sn_refreshing: N` when background fetch is in flight; frontend polls until covers appear

### Import CSV (`/api/import/csv`)
- Accepts a Discogs-format CSV (from Discogs export or SN export)
- Standard Discogs columns: `Catalog#`, `Artist`, `Title`, `Label`, `Format`, `Released`, `release_id`, `CollectionFolder`, `Collection Media Condition`, `Collection Sleeve Condition`
- Custom fields: `Collection [Field Name]` columns → resolved via `discogs_field_mappings`
- SN export fallback: tries `SN_{col}` then bare `{col}` for SN-specific columns
- **`db_only` is always empty** — CSV import is partial; records absent from the CSV are untouched
- Returns a diff object (same shape as `/api/collection/preview`) — apply via `/api/collection/sync`

### Export CSV (`/api/export`)
- Standard Discogs column names for Discogs-sourced fields
- `Collection [Field Name]` for mapped custom fields
- `SN_{col}` prefix for unmapped SN fields (`SN_retailer`, `SN_price`, etc.) and SN extras (`SN_id`, `SN_instance_id`, `SN_is_new`, `SN_cover_file`)
- Ordering: `instance_id` ASC, then `id` ASC

### Diff computation (`compute_diff`)
- Compares prospective items (from Discogs or CSV) against the SN DB
- Matches by `instance_id` first, falls back to `discogs_id`
- Compares `DISCOGS_SOURCED` fields + any mapped custom fields
- Uses `None`-safe string comparison: `None` → `""`, not `str(None or "")`
- For `price`, `pp`, `valuation`: treats `None` (blank from source) as equivalent to `0` (DB default for "not entered") — avoids false positives when fields aren't mapped

## Frontend Architecture (`static/index.html`)

Everything lives in one file. No framework, no build step.

### Global state
```js
records           // array — full dataset from API
currentView       // 'table' | 'tile'
editingId         // null or record id
fetchedMeta       // Discogs preview data during add/edit
sortCol           // active sort column key or null
sortDir           // 'asc' | 'desc' | null
showValuations    // bool — toggle collection value display
showTags          // bool — toggle format filter bar visibility
filterFormat      // active format tag string, or null
diffData          // last sync diff payload
syncSource        // 'discogs' | 'csv' — controls sync modal behaviour
hideObviousFormats // bool — global on/off for format tag hiding
hiddenFormatTags  // Set<string> — tags to hide from filter bar
```

### localStorage persistence
All UI state is persisted via `lsGet(key, fallback)` / `lsSet(key, val)` helpers (prefixed `sn_`). `restoreLocalState()` runs on `DOMContentLoaded` before any data fetch. Persisted keys: `view`, `showValuations`, `showTags`, `groupByArtist`, `toolbarExpanded`.

### Key functions

| Function | Purpose |
|---|---|
| `loadRecords()` | Fetch `/api/records`, update state, render, stats, retailer list |
| `getFiltered()` | Filter by search — no sorting (pure filter) |
| `applySortCol(rows)` | Sort array by `sortCol`/`sortDir` |
| `headerSort(col)` | Cycle sort: asc → desc → clear |
| `renderTable()` | Build sortable table with optional artist grouping |
| `renderTiles()` | Build cover art grid (always sorted artist → year) |
| `rowHtml(r)` | Generate single table row HTML |
| `openAdd()` / `openEdit(id)` | Open add/edit form modal |
| `fetchDiscogs()` | Fetch `/api/discogs/{id}`, populate form fields |
| `startCoverPoll(n)` | Poll `loadRecords()` every 8s until n new covers appear (max 40 polls) |
| `updateStats()` | Update KPI bar: Total Records, Collection Cost, Collection Value |
| `formatTags(s, respectHide)` | Parse format string into tag array; filters `hiddenFormatTags` when enabled |
| `condLabel(c)` | Expand condition code to label; returns `'Unknown'` for blank |
| `fmtDate(s)` | YYYY-MM-DD → DD/MM/YYYY for display |
| `toISODate(s)` | DD/MM/YYYY → YYYY-MM-DD for date input |
| `lsGet(key, fallback)` / `lsSet(key, val)` | localStorage helpers (prefix `sn_`) |
| `restoreLocalState()` | Rehydrate all UI state from localStorage on load |
| `renderSyncPreview(diff)` | Render sync/import diff modal; respects `syncSource` |
| `importCsv(input)` | POST CSV → sets `syncSource='csv'` → opens sync modal |
| `openSettings()` | Open settings modal; reloads field mapping in-place |
| `saveSettings()` | Persist settings; stays open; refreshes field mapping if username changed |

### Views
- **Table:** Clickable column headers cycle asc/desc/clear. "Group by artist" toggle overrides column sort with artist A-Z + year.
- **Tiles:** Always sorted artist A-Z → year. Clicking a tile opens detail modal.

### Toolbar
Collapsible via the "Options ▾" button in the header. Collapsed by default on mobile (`< 768px`), expanded on desktop. State persisted to localStorage.

### Modals
- `modal-detail` — read-only record detail (tile click)
- `modal-form` — add/edit form with Discogs lookup
- `modal-discogs-sync` — diff preview; shared between Discogs collection sync and CSV import. `syncSource` controls labels and available actions (CSV hides "Discogs →" direction)
- `modal-settings` — Display settings, Discogs config + field mapping, Data (import/export), Danger Zone. **Save stays open** (reload fields in-place); Close button dismisses.

### Settings modal sections (top to bottom)
1. **Display** — Clean artists, Include P&P, Hide format tags (toggle + tag list)
2. **Discogs** — Username, Token, Refresh Metadata, Field Mapping, Sync Collection
3. **Data** — Import from CSV, Export to CSV
4. **Danger Zone** — Delete All Records (records only), Format Database (factory reset), Clear Image Cache

## Discogs Grading Scale
S (Sealed) → M → NM → VG+ → VG → G+ → G → F → P

## Important Behaviours

- **Date storage:** Always YYYY-MM-DD in DB. `normalise_date()` (backend) and `toISODate()` (frontend) handle DD/MM/YYYY on the way in. `fmtDate()` converts to DD/MM/YYYY for display only.
- **Cover images:** Cached on first fetch; re-download skipped if file already exists. Multiple images per release stored in `images` table (up to 8). User can set cover via detail modal.
- **Valuation:** Per-record, sourced from `/marketplace/stats/{id}` on fetch/refresh. Summed for the Collection Value KPI.
- **is_new:** Three-state — `NULL` (unknown/not set, no badge shown), `0` (Pre-Owned), `1` (New). Records imported without a mapped `is_new` field get NULL.
- **Rate limiting:** Single process-wide broker (`_discogs_acquire()`) enforces 55 req/min. All Discogs calls use `discogs_get()` / `discogs_post()`. No manual sleep/batch logic.
- **Background refresh:** After collection sync creates new records, `_refresh_new_records` runs as a FastAPI background task. Frontend calls `startCoverPoll(n)` to reload until covers appear.
- **SPA routing:** `GET /{full_path:path}` serves static files or falls back to `index.html`. API routes are defined before this catch-all.
- **Empty DB:** `list_records` catches `OperationalError`, calls `init_db()`, returns `[]` rather than 500.
- **No schema migrations:** `init_db()` uses `CREATE TABLE IF NOT EXISTS` only. Assume fresh installs. To reset: delete `/data/sleevenotes.db`.
