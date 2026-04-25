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

## Git Workflow

Always create a feature branch before making any code or config changes. Never commit directly to `main`. Branch naming: `fix/<slug>` for bugs, `feat/<slug>` for features, `docs/<slug>` for documentation.

## Releases

Docker images are published to `ghcr.io/sidtheturtle/sleevenotes` on version tag pushes only — main branch pushes do not trigger a build.

**Version strategy:** `vMAJOR.MINOR.PATCH` — currently on `v1.x.y`. New features increment minor, bug fixes increment patch.

**To cut a release:** `gh release create vX.Y.Z --title "vX.Y.Z" --notes "..." --target main`

This triggers CI to publish both `X.Y.Z` and `latest` to GHCR. Users pin their `compose.yml` to a specific version for rollback: `image: ghcr.io/sidtheturtle/sleevenotes:1.6.0`

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
| `show_valuations` | `true` | Show Collection Value KPI and per-record valuation column |
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

### `wishlist` table

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `master_id` | TEXT UNIQUE | Discogs master release ID (plain numeric string, no prefix) |
| `artist` | TEXT | |
| `title` | TEXT | |
| `cover_file` | TEXT | Cached image filename — prefixed `m{master_id}` to avoid collision with release images |
| `added_at` | TEXT | Auto timestamp |
| `notes` | TEXT | |
| `fulfilled` | INTEGER | 0 = wanted, 1 = fulfilled |
| `year` | INTEGER | Master release year |
| `genres` | TEXT | Comma-separated genres from Discogs |
| `styles` | TEXT | Comma-separated styles from Discogs |
| `lowest_price` | REAL | Discogs lowest listing price at time of add |
| `num_for_sale` | INTEGER | Discogs for-sale count at time of add |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Returns `{"status":"ok","dev":bool}` — used for server reachability probing; `dev` drives the dev banner |
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
| GET | `/api/wishlist/search` | Search Discogs master releases (`?q=`) |
| GET | `/api/wishlist` | List wishlist items (`?include_fulfilled=true` to include fulfilled) |
| POST | `/api/wishlist` | Add a master release to the wishlist (fetches `/masters/{id}`, downloads cover) |
| PUT | `/api/wishlist/{id}` | Update notes and/or fulfilled status |
| DELETE | `/api/wishlist/{id}` | Delete a wishlist item |

### Wishlist add (`POST /api/wishlist`)
- Accepts `{master_id, notes}`; strips leading `m` from master_id
- Calls `/masters/{id}` — extracts artist, title, year, genres, styles, lowest_price, num_for_sale
- Downloads and caches the first master image to `/data/images/` with `m{master_id}` prefix
- Returns 409 if master_id already on wishlist

### Discogs rate limiter
All outbound Discogs API calls go through `discogs_get()` / `discogs_post()` wrappers that enforce a 55 req/min sliding-window limit (buffer under Discogs' 60/min). The limiter is process-wide — no manual sleep/batch logic anywhere else. On a 429 response, it waits 60 s and retries once. Image CDN calls (`i.discogs.com`) bypass the limiter — they are not API calls.

### Discogs fetch (`/api/discogs/{id}`)
- Accepts `r12345678` or `12345678`
- Makes 2 concurrent Discogs calls: `/releases/{id}` + `/marketplace/stats/{id}`
- Returns artist, title, label, cat_no, year, format, cover_file, valuation, and `wishlist_match` (unfulfilled wishlist item matching this release's `master_id`, or null)
- `wishlist_match` includes `{id, artist, title, notes}` — notes used for porting to collection record on fulfillment
- Downloads and caches all images (up to 8) to `/data/images/`; populates `tracklist` table

### Record refresh (`/api/records/{id}/refresh`)
- Updates Discogs-sourced fields only: artist, title, label, cat_no, year, format, cover_file, valuation, tracklist, images
- Preserves all user-entered fields

### Collection sync (`/api/collection/sync`)
- Accepts `{to_sleevenotes: [...], to_discogs: [...]}` payload
- All SN records (created or updated) trigger a background `_refresh_new_records` task (images + tracklist + valuation)
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
- Ordering: `id` ASC

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
currentSection    // 'collection' | 'wishlist'
currentView       // 'table' | 'tile'
editingId         // null or record id
fetchedMeta       // Discogs preview data during add/edit
sortCol           // active sort column key or null
sortDir           // 'asc' | 'desc' | null
showValuations    // bool — show Collection Value KPI and valuation column (DB-backed)
showTags          // bool — toggle format filter bar visibility
filterFormat      // active format tag string, or null
diffData          // last sync diff payload
syncSource        // 'discogs' | 'csv' — controls sync modal behaviour
hideObviousFormats // bool — global on/off for format tag hiding
hiddenFormatTags  // Set<string> — tags to hide from filter bar
wishlistItems     // array — merged server + pending items for display (rebuilt by loadWishlist)
showFulfilled     // bool — show fulfilled items in wishlist view
serverReachable   // bool — false when internet present but server unreachable
_reachabilityPollTimer // setTimeout handle for backoff reachability polling
pendingQueue      // array — in-memory mirror of IDB wishlist_queue (new items queued offline)
pendingUpdates    // array — in-memory mirror of IDB wishlist_updates (edits queued offline)
_serverWishlistItems  // array — last fetched server wishlist data; pendingUpdates applied on top
_lastSearchResults    // array — last wishlist search results; used by addToWishlist for metadata
```

Two-level nav: top-level **Collection / Wishlist** switch (always visible), with **Table / Tile** as sub-options within **both** sections. `setSection(s)` handles top-level nav; `setView(v)` handles sub-views. Only `'table'`/`'tile'` are saved to localStorage — app always opens to collection.

### localStorage persistence
All UI state is persisted via `lsGet(key, fallback)` / `lsSet(key, val)` helpers (prefixed `sn_`). `restoreLocalState()` runs on `DOMContentLoaded` before any data fetch. Persisted keys: `view` (table/tile only — wishlist never persisted as startup view), `showTags`, `groupByArtist`, `showFulfilled`. `showValuations` is DB-backed via the `settings` table, not localStorage.

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
| `loadWishlist()` | Fetch `/api/wishlist` (always tries — SW serves from cache if server down), apply `pendingUpdates`, merge `pendingQueue` items, rebuild `wishlistItems`, render and update stats |
| `renderWishlist()` | Delegates to `renderWishlistTiles()` when `currentView === 'tile'`, otherwise builds sortable table; pending items show Pending badge instead of added date |
| `renderWishlistTiles()` | Build wishlist cover art grid sorted artist → year; pending items show corner Pending badge and ⏳ placeholder if no thumb |
| `openWishlistSearchModal(prefill)` | Open master release search modal; blocked only when `!navigator.onLine`; shows offline info banner when server unreachable |
| `doWishlistSearch()` | When server reachable: calls `/api/wishlist/search`. When offline: calls Discogs API directly (unauthenticated, 25 req/min). Stores results in `_lastSearchResults` |
| `addToWishlist(masterId)` | When online: POST to `/api/wishlist`. When offline: saves to IDB `wishlist_queue` via `saveToQueue()`, shows pending in list |
| `deleteWishlistItem(id)` | DELETE item, reload wishlist |
| `openWishlistDetail(id)` | Negative id → `openPendingWishlistDetail`. Otherwise: cover, metadata, fulfilled checkbox + notes textarea, Save (queues offline) + Delete (disabled offline) |
| `openPendingWishlistDetail(id)` | Detail modal for IDB-queued items: thumb, metadata, editable notes (saved to IDB), Delete removes from queue — all works offline |
| `openOfflineDB()` | Open IndexedDB `sn_offline` v2; creates `wishlist_queue` (autoIncrement) and `wishlist_updates` (keyed by `wishlist_id`) on upgrade |
| `initPendingQueue()` | Load both IDB stores into `pendingQueue` and `pendingUpdates` on startup |
| `saveToQueue(item)` | Add new wishlist item to IDB `wishlist_queue`, update `pendingQueue` in memory |
| `removeFromQueue(idbKey)` | Delete from IDB `wishlist_queue`, update `pendingQueue` |
| `saveUpdateToQueue(update)` | Upsert `{wishlist_id, notes, fulfilled}` to IDB `wishlist_updates`, update `pendingUpdates` |
| `removeUpdateFromQueue(wishlistId)` | Delete from IDB `wishlist_updates`, update `pendingUpdates` |
| `updateQueueItemNotes(idbKey, notes)` | Update notes on an existing IDB `wishlist_queue` item in place |
| `flushPendingQueue()` | On reconnect: POST each `wishlist_queue` item, PUT each `wishlist_updates` item; removes from IDB on success/409; reloads wishlist and toasts count |
| `splitDiscogsTitle(combined)` | Split "Artist - Title" Discogs search string into `{artist, title}` for pending item display |
| `setSection(section)` | Top-level nav: sets `currentSection`, updates nav buttons, calls `applyToolbarSwitches`, loads/renders appropriate view |
| `applyToolbarSwitches(s)` | Show/hide collection vs wishlist switches; `collection-view-toggle` always visible (both sections support Table/Tile); update search placeholder |
| `apiFetch(url, opts)` | Wrapper around `fetch` for all `/api/` calls — catches `TypeError` and triggers `probeHealth()` if online |
| `checkHealth()` | `fetch('/api/health')` with 5s timeout; returns bool — uses plain `fetch`, not `apiFetch`, to avoid recursion |
| `probeHealth()` | Calls `checkHealth()` and passes result to `setServerReachable()` |
| `setServerReachable(bool)` | Updates `serverReachable`, calls `updateOnlineState()`, starts/cancels backoff polling, toasts on reconnect, calls `flushPendingQueue()` on reconnect |
| `scheduleReachabilityCheck(attempt)` | Backoff poll: 10s → 30s → 60s; only runs while app is visible and server unreachable |
| `updateOnlineState()` | Sets `body.offline` class and banner for both offline states; disables write actions |

### Views
- **Table (Collection):** Clickable column headers cycle asc/desc/clear. "Group by artist" toggle overrides column sort with artist A-Z + year.
- **Tiles (Collection):** Always sorted artist A-Z → year. First tap shows overlay; second tap (or overlay button) opens detail modal.
- **Table (Wishlist):** Sortable table (artist, title, year, added date). No inline search filtering — the search bar is a CTA that opens the master release search modal on Enter.
- **Tiles (Wishlist):** Cover art grid sorted artist → year. Single click opens detail modal directly (no two-tap selection model).
- Both wishlist views: Format filter bar hidden. Toolbar shows "Show fulfilled" toggle only. Switching sections clears the search bar.

### Toolbar
Always visible (no collapse toggle). Single nav row: `[Collection] [Wishlist]` pair, separator, `[Table] [Tiles]` pair (always shown for both sections), then search and context-sensitive toggles.

### Modals
- `modal-detail` — read-only record detail (tile click)
- `modal-form` — add/edit form with Discogs lookup
- `modal-discogs-sync` — diff preview; shared between Discogs collection sync and CSV import. `syncSource` controls labels and available actions. "Discogs →" direction is hidden for CSV imports and for records where only core fields (artist, title, label, cat_no, year, format) differ
- `modal-settings` — Display settings, Discogs config + field mapping, Data (import/export), Danger Zone. **Save stays open** (reload fields in-place); Close button dismisses.
- `modal-wishlist-search` — Discogs master release search; results show Add/Queued/On wishlist/Fulfilled per item. Shows slate info banner when server unreachable (searching Discogs directly)
- `modal-wishlist-detail` — Wishlist item detail: cover, metadata, fulfilled checkbox, notes textarea, Save + Delete. Save queues offline for server items; Delete disabled offline for server items, always enabled for pending items

### Settings modal sections (top to bottom)
1. **Display** — Clean artists, Include P&P, Show Valuations, Hide format tags (toggle + tag list). **All display toggles are staged — state only applies on Save, not on toggle.**
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
- **Wishlist fulfilled prompt:** When saving a new collection record, if the fetched Discogs release has a `master_id` matching an unfulfilled wishlist item (`wishlist_match` in the fetch response), the user is prompted to mark it fulfilled. Wishlist `notes` are appended to the collection record's notes at the same time (empty collection notes → copy; existing notes → append with newline).
- **Wishlist fulfilled toggle:** The detail modal shows a checkbox for fulfilled status, saved together with notes via the Save button. This replaces the former instant "Mark Fulfilled" action — changes are reversible until saved.
- **Wishlist cover prefix:** Master release covers are stored as `m{master_id}_01.jpeg` to avoid filename collision with release images (`r{release_id}_...`).
- **Tracklist loading:** Fetched eagerly when a record detail modal opens (not gated on the Tracklist tab click), so the SW caches the response for offline use on that same visit.
- **PWA / service worker (`static/sw.js`):**
  - Install: precaches app shell (`/`, `manifest.json`, icons) — prevents pull-to-refresh showing the browser offline page
  - `/images/*`: cache-first — cover images and any other record images load offline after first view
  - `/api/records`, `/api/wishlist`, `/api/settings` (GET only): network-first with SW cache fallback — collection and wishlist survive page refresh with server down
  - `/api/health`: always network-only — must hit the server for reachability detection
  - All other `/api/*`: network-only (mutations, Discogs fetches, etc.)
  - Background Sync: SW flushes both IDB queues (`wishlist-sync` tag) on Android when app is backgrounded
- **Two-state offline detection:** The app distinguishes two offline states, each with its own banner:
  - **Read-Only Mode** (`navigator.onLine === false`) — no internet, amber banner `#7A4800`. Fully read-only.
  - **Offline Mode** (`navigator.onLine === true` but `/api/health` fails) — server unreachable, slate banner `#3D4A5C`. Collection read-only from SW cache; wishlist search, add, and edit all work via IndexedDB queue.
  - Both states set `body.offline` and disable collection write actions.
  - Detection is event-driven: probe on load, on `window 'online'`, on any `apiFetch` TypeError, and on `visibilitychange` visible. Backoff polling (10s → 30s → 60s) only runs while the app is visible and the server is unreachable — cancelled immediately on `visibilitychange` hidden so backgrounding the app stops all polling.
- **Offline wishlist queue (IndexedDB `sn_offline` v2):**
  - `wishlist_queue` (autoIncrement key `idb_key`): new items added offline. Each record: `{master_id, notes, queued_at, title, year, thumb}`. Pending items merged into `wishlistItems` with negative IDs (`-(idb_key)`) for display.
  - `wishlist_updates` (key `wishlist_id`): notes/fulfilled edits made offline. Upsert — only latest edit per item is kept. Applied to `_serverWishlistItems` before rendering so display reflects queued state immediately.
  - Both queues flushed on reconnect via `flushPendingQueue()` and by Background Sync on Android.
  - Discogs token never sent to browser; offline search uses unauthenticated Discogs API (25 req/min, no thumbnails returned — ♪ placeholder shown).
