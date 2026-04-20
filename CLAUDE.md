# SleeveNotes

A personal vinyl record collection manager. Single-page app backed by a FastAPI/SQLite server, containerised with Docker.

## Stack

- **Backend:** Python 3.12, FastAPI, SQLite, httpx
- **Frontend:** Vanilla JS SPA (`static/index.html`) — no build step
- **Container:** Docker Compose, port 2026, persistent `/data` volume
- **Discogs API:** Token from `DISCOGS_TOKEN` env var

## Project Structure

```
app.py              # FastAPI backend — all routes, DB, helpers
static/index.html   # Entire frontend — HTML, CSS, JS in one file
Dockerfile
compose.yml
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

Single table: `records`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `discogs_id` | TEXT | Format: `r12345678` |
| `cat_no` | TEXT | Catalog number |
| `artist` | TEXT | Comma-separated if multiple |
| `title` | TEXT | |
| `label` | TEXT | |
| `year` | INTEGER | Release year |
| `format` | TEXT | e.g. "Vinyl, LP, Album" |
| `cover_file` | TEXT | Cached image filename in `/data/images/` |
| `is_new` | INTEGER | 0/1 boolean |
| `orig_cond` | TEXT | S/M/NM/VG+/VG/G+/G/F/P |
| `curr_cond` | TEXT | Same scale |
| `status` | TEXT | "In Collection" / "Purchased" / "Returned" |
| `retailer` | TEXT | |
| `order_ref` | TEXT | |
| `purchase_date` | TEXT | ISO 8601 (YYYY-MM-DD) |
| `price` | REAL | Item cost (GBP) |
| `pp` | REAL | Postage & packaging (GBP) |
| `notes` | TEXT | |
| `valuation` | REAL | Discogs lowest listing price |
| `created_at` | TEXT | Auto timestamp |

Schema migrations (e.g. adding `valuation`) are handled via guarded `ALTER TABLE` in `init_db()` — add new ones there.

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/records` | List records (`?show_returned=false`) |
| POST | `/api/records` | Create record |
| PUT | `/api/records/{id}` | Update record |
| DELETE | `/api/records/{id}` | Delete record |
| GET | `/api/discogs/{release_id}` | Fetch metadata + valuation from Discogs |
| POST | `/api/records/{id}/refresh` | Re-fetch Discogs data for existing record |
| POST | `/api/import` | Upload pipe-delimited CSV |
| GET | `/api/export` | Download pipe-delimited CSV |
| POST | `/api/admin/format` | **DESTRUCTIVE** — delete all records |

### Discogs fetch (`/api/discogs/{id}`)
- Accepts `r12345678` or `12345678`
- Fetches `/releases/{id}` — returns artist, title, label, cat_no, year, format, cover_file, valuation
- `valuation` comes from `data["lowest_price"]` in the release response (not the marketplace API)
- Downloads and caches cover image to `/data/images/{release_id}.{ext}`

### Record refresh (`/api/records/{id}/refresh`)
- Updates Discogs-sourced fields only: artist, title, label, cat_no, year, format, cover_file, valuation
- Preserves all user-entered fields (price, pp, date, retailer, notes, status, condition, etc.)

### Import CSV
- Pipe-delimited (`|`), first row is header
- Column aliases: `discogsId`→`discogs_id`, `catNo`→`cat_no`, `origCond`→`orig_cond`, `currCond`→`curr_cond`, `orderRef`→`order_ref`
- Date normalisation: accepts DD/MM/YYYY, D/M/YYYY, YYYY-MM-DD
- Deduplication: skips rows where source `id` or `discogs_id` already exists in DB (checked both within-file and against DB)

## Frontend Architecture (`static/index.html`)

Everything lives in one file. No framework, no build step.

### Global state
```js
records      // array — full dataset from API
currentView  // 'table' | 'tile'
editingId    // null or record id
fetchedMeta  // Discogs preview data during add/edit
sortCol      // active sort column key or null
sortDir      // 'asc' | 'desc' | null
```

### Key functions

| Function | Purpose |
|---|---|
| `loadRecords()` | Fetch `/api/records`, update state, render, stats, retailer list |
| `getFiltered()` | Filter by search + status — no sorting (pure filter) |
| `applySortCol(rows)` | Sort array by `sortCol`/`sortDir` |
| `headerSort(col)` | Cycle sort: asc → desc → clear |
| `renderTable()` | Build sortable table with optional artist grouping |
| `renderTiles()` | Build cover art grid (always sorted artist → year) |
| `th(col, label, cls)` | Generate sortable `<th>` with arrow indicator |
| `rowHtml(r)` | Generate single table row HTML |
| `openAdd()` / `openEdit(id)` | Open add/edit form modal |
| `fetchDiscogs()` | Fetch `/api/discogs/{id}`, populate form fields |
| `doFetchRange(start, end)` | Bulk refresh batch with 2s delay between records |
| `fmtDate(s)` | YYYY-MM-DD → DD/MM/YYYY for display |
| `toISODate(s)` | DD/MM/YYYY → YYYY-MM-DD for date input |

### Views
- **Table:** Clickable column headers cycle asc/desc/clear. "Group by artist" toggle (hidden in tile view) overrides column sort with artist A-Z + year.
- **Tiles:** Always sorted artist A-Z → year. Clicking a tile opens detail modal.

### Modals
- `modal-detail` — read-only record detail (opened from tile click)
- `modal-form` — add/edit form with Discogs lookup
- `modal-import` — CSV upload
- `modal-settings` — batch Discogs refresh + Format DB (danger zone with safety toggle)

## Discogs Grading Scale
S (Sealed) → M → NM → VG+ → VG → G+ → G → F → P

## Important Behaviours

- **Date storage:** Always YYYY-MM-DD in DB. `normalise_date()` (backend) and `toISODate()` (frontend) handle legacy DD/MM/YYYY on the way in. `fmtDate()` converts to DD/MM/YYYY for display only.
- **Cover images:** Cached on first fetch; subsequent fetches with the same release ID are skipped unless the file is missing. On refresh, falls back to existing `cover_file` if download fails.
- **Valuation:** Sourced from `lowest_price` field in the Discogs `/releases/{id}` response — no separate marketplace API call needed.
- **Rate limiting:** Discogs allows 60 req/min. Bulk refresh fires 5 records concurrently per batch with a 5-second pause between batches (5 req per 5s = 60/min). Each refresh is 1 Discogs API call.
- **SPA routing:** `GET /{full_path:path}` serves matching static files or falls back to `index.html`. API routes are defined before this catch-all and always take priority.
- **Empty DB:** `list_records` catches `OperationalError` (table missing after DB deletion while server is live), calls `init_db()`, and returns `[]` rather than 500.
