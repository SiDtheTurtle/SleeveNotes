# Plan: FR #73 — Wishlist Versions + Wantlist Sync (Second Attempt)

## Context

SleeveNotes has a wishlist of Discogs _master_ releases. Masters are top-level entries (e.g. "I Quit" by HAIM); beneath them sit many _versions_ (specific pressings: coloured vinyl, limited editions, region variants). Currently there is no way to shortlist specific pressings, and no integration with the Discogs user wantlist (which is version/release-level).

**Core architectural insight:** A Discogs wantlist item is just a release — the same entity as a collection record. Rather than a separate `wishlist_versions` table, wishlist pressings live in the existing `records` table, distinguished by an `is_wishlist` flag. This gives full Discogs metadata (images, tracklists) for free via the existing refresh flow. Fulfilling a version = flip the flag, fill in purchase details — no data migration.

The `wishlist` table remains as-is: it anchors master releases. Versions/pressings hang beneath it in `records` via a `wishlist_id` FK.

---

## Critical Files

| File | Role |
|---|---|
| `app.py` | Backend — schema, helpers, routes |
| `static/index.html` | Frontend SPA — all JS, HTML, CSS |
| `static/sw.js` | Service worker — caching strategy |

---

## Phase 1 — Schema Changes ✅ DONE

### 1.1 — Add columns to `records` table in `init_db()` (app.py)

Six new columns added (plan originally had four; `country` and `discogs_notes` added during implementation):

```sql
is_wishlist    INTEGER DEFAULT 0,   -- 0 = collection item, 1 = wishlist pressing
wishlist_id    INTEGER,             -- FK → wishlist.id (NULL for collection items)
in_wantlist    INTEGER DEFAULT 0,   -- 1 = synced to Discogs wantlist
identifiers    TEXT,                -- JSON [{type, value}] — barcodes, matrix nos, etc.
discogs_notes  TEXT,                -- read-only; notes field from Discogs wantlist item
country        TEXT                 -- country of pressing
```

`discogs_notes` is populated on wantlist sync from Discogs and displayed read-only in the UI. The user's own `notes` field remains editable and is never pushed to Discogs. This prevents two-way sync conflicts.

### 1.2 — Column guard in `init_db()` (app.py) ✅ DONE

ALTER TABLE guards run on startup for all 6 new columns. Pattern: `try: conn.execute(ALTER TABLE...); except: pass`.

### 1.3 — Partial unique index ✅ DONE

```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_wishlist_version
ON records (wishlist_id, discogs_id)
WHERE is_wishlist = 1 AND deleted_at IS NULL
```

---

## Phase 2 — Backend: New & Modified Endpoints ✅ DONE

All follow existing patterns: `discogs_get()` for Discogs calls, `get_db()` context manager, `get_discogs_headers()` for auth.

### 2.1 — `GET /api/records` modified ✅

Filter: `AND (is_wishlist = 0 OR is_wishlist IS NULL)` — wishlist pressings never appear in collection.

### 2.2 — New Pydantic models ✅

- `WishlistVersionIn`: `discogs_id` + preview metadata fields (title, label, cat_no, year, format, country) — metadata stored immediately so versions panel shows details before background refresh completes
- `WishlistVersionUpdateIn`: `notes` (optional)
- `WantlistSyncPayload`: `to_discogs` (list of record_ids), `to_sleevenotes` (list of {discogs_id, master_id, notes})

### 2.3 — `GET /api/wishlist/{wishlist_id}/versions` ✅

Returns all non-deleted `is_wishlist=1` records for the given wishlist item, ordered year/country.

### 2.4 — `GET /api/masters/{master_id}/releases` ✅

Fetches Discogs `masters/{id}/versions?format=Vinyl&per_page=100`, up to 5 pages. **Note:** post-filter by "Vinyl" in format string was removed — Discogs server-side filter handles it; post-filtering dropped all results since format strings are like "LP, Album" (not "Vinyl, LP, Album").

### 2.5 — `GET /api/release/{release_id}/info` ✅

Full Discogs release metadata including `identifiers` array (barcodes, matrix numbers). Cached by SW.

### 2.6 — `POST /api/wishlist/{wishlist_id}/versions` ✅

Stores preview metadata immediately on INSERT (no waiting for background refresh), then triggers `_refresh_wishlist_version` background task for full metadata + images.

### 2.7 — `DELETE /api/wishlist/versions/{record_id}` ✅

Soft-delete: `UPDATE records SET deleted_at = datetime('now') WHERE id = ? AND is_wishlist = 1`.

### 2.8 — `PUT /api/wishlist/versions/{record_id}` ✅

Updates `notes` field.

### 2.9 — `POST /api/wishlist/versions/{record_id}/fulfill` ✅

`UPDATE records SET is_wishlist = 0, wishlist_id = NULL WHERE id = ? AND is_wishlist = 1`. Returns `{ok: true, record_id: id}`.

### 2.10 — `GET /api/wantlist/preview` ✅

Compares SN wishlist versions against Discogs user wantlist. Returns `{sn_only, discogs_only, in_sync_count}`.

### 2.11 — `POST /api/wantlist/sync` ✅

Bidirectional: push SN versions to Discogs wantlist (`PUT /users/{u}/wants/{id}`), import Discogs wants into SN (create master + version records). Returns `{ok: true, exported: N, imported: N}`.

### Route ordering note

`/api/wishlist/versions/{id}` must be defined **before** `/api/wishlist/{id}` in app.py — FastAPI routes match in order, and `versions` would otherwise be captured as a wishlist_id.

---

## Phase 3 — Frontend: Version UI ✅ DONE

### 3.1 — `openWishlistDetail` extended ✅

Versions panel appended to modal body. `loadVersions(wishlistId)` → `GET /api/wishlist/{id}/versions`. Modal widened to max-width:640px.

### 3.2 — `openVersionBrowser(wishlistId, masterId)` ✅

Opens `modal-version-browser`. Table with `table-layout:fixed` + `<colgroup>` widths to prevent text overlap. Shortlisted versions show "Shortlisted ✓" (cross-referenced against server versions + `pendingVersionQueue`).

### 3.3 — `toggleVersionStaged(wishlistId, discogs_id, isShortlisted, versionRecordId)` ✅

Renamed from `toggleVersion`. Changes are staged in `_stagedVersionChanges` and only applied when the main Save button is pressed. Shortlist: stages a POST with preview metadata read from browser table row cells. Remove: stages a DELETE. On shortlist, captures thumb URL from table row `<img>` into `_versionThumbs[discogs_id]` for immediate display.

### 3.4 — `fulfillVersion(recordId, wishlistId)` ✅

1. Opens `modal-fulfill-version` via `confirmYesNo()` prompt
2. On confirm: POST fulfill endpoint, set `_pendingWishlistFulfill` global with parent wishlist item
3. `openEdit(recordId)` — edit modal opens pre-filled
4. `saveRecord()` picks up `_pendingWishlistFulfill` (same as `wishlist_match` for new records) → fires fulfilled prompt

### 3.5 — `openWantlistSyncModal()` ✅

Settings → Discogs → "Sync Discogs wantlist…". Preview modal redesigned to match collection sync visual patterns: monospace colour-coded section headers (green = new from Discogs, blue = only in SN), border dividers, direction badges, dynamic "Sync (N)" button count. Sync button POSTs selections.

### 3.6 — New modals ✅

- `modal-version-browser` (760px) — browse pressings
- `modal-wantlist-sync` (600px) — sync preview
- `modal-fulfill-version` (440px) — offline fulfill: collect purchase details to queue in IDB

### Global state additions

```js
pendingVersionQueue        // array — in-memory mirror of IDB version_queue
pendingVersionRemoves      // array — in-memory mirror of IDB version_removes
pendingVersionFulfillments // array — in-memory mirror of IDB version_fulfillments
_pendingWishlistFulfill    // object|null — parent wishlist item for fulfill prompt
_versionThumbs             // {discogs_id: thumbUrl} — CDN thumb fallback until cached image arrives
_stagedVersionChanges      // {wishlistId, toAdd[], toRemove Set, toFulfill Set} — staged until Save
```

### Thumbnail fallback pattern

```js
const rid = String(v.discogs_id || '').replace(/^r/, '');
const thumbFallback = _versionThumbs[rid];
const thumbSrc = v.cover_file ? `/images/${esc(v.cover_file)}` : (thumbFallback || null);
```

`_versionThumbs` is populated at shortlist time from the browser table row's `<img>` src (Discogs CDN URL), so the thumbnail shows immediately while background refresh downloads and caches the image.

---

## Phase 4 — Service Worker (sw.js) ✅ DONE

`CACHED_DATA` extended:

```js
const CACHED_DATA = ['/api/records', '/api/wishlist', '/api/settings', '/api/masters/', '/api/release/'];
```

**SW clone bug fix:** `resp.clone()` must be called synchronously before any `await` or `.then()` gap — body is already consumed by `return resp` otherwise. Both network-first handlers now clone before opening cache:

```js
if (resp.ok) { const clone = resp.clone(); caches.open(CACHE).then(c => c.put(e.request, clone)); }
```

### IDB v3 (sn_offline) ✅ COMPLETE

Both `openOfflineDB()` (index.html) and `openSwDB()` (sw.js) are at v3 with all five stores: `wishlist_queue`, `wishlist_updates`, `version_queue`, `version_removes`, `version_fulfillments`. Both `flushPendingQueue()` (index.html) and `flushOfflineQueue()` (sw.js) process all five stores on reconnect, with version adds running before removes/fulfillments.

### `cacheAllVersions()` ✅

Replaced `prefetchVersionData()`. Fires after every `loadWishlist()` — fetches `/api/wishlist/{id}/versions` for all server wishlist items in parallel (pure DB reads, no Discogs calls). Primes SW cache for offline use. After all fetches complete, re-renders the wishlist to show/update "Syncing…" badges.

**Key difference from original `prefetchVersionData()`:** Does not call `/api/release/{id}/info`. Discogs API calls are only made from the wantlist sync buttons in Settings and the version browser Details button — never on page load.

---

## Offline Behaviour

| State | Versions list | Browse pressings | Shortlist / Remove | Add to collection |
|---|---|---|---|---|
| Online | ✓ live | ✓ | ✓ | ✓ |
| Offline (server down) | ✓ SW cache (pre-loaded by `cacheAllVersions`) | ✓ SW cache (if visited) | ✓ via IDB queue | ✓ synced versions only |
| Read-only (no internet) | ✓ SW cache (pre-loaded by `cacheAllVersions`) | ✓ SW cache (if visited) | ✗ disabled | ✗ disabled |

---

## Key Reused Code

| Existing code | Reused for |
|---|---|
| `_refresh_new_records` background task pattern | `_refresh_wishlist_version` for new shortlisted versions |
| `openEdit(id)` + `saveRecord()` | Add purchase details when fulfilling a version |
| `wishlist_match` fulfilled prompt in `saveRecord()` | `_pendingWishlistFulfill` bridges version fulfill into existing flow |
| `discogs_get()` / `discogs_post()` | All new Discogs API calls |
| Soft-delete pattern (`deleted_at`) | Removing wishlist versions |
| `apiFetch()`, `esc()`, `showToast()` | All new frontend code |

---

## Status

**All four phases implemented and tested on `feat/wishlist-versions-v2`.** Ready for final review before merge to main.

### Bugs found and fixed during implementation

1. **"No vinyl pressings found"** — post-filter on "Vinyl" in format string dropped everything (Discogs returns "LP, Album" not "Vinyl, LP"). Fix: removed post-filter.
2. **Text overlap in version browser table** — Fix: `table-layout:fixed` + `<colgroup>` column widths + `overflow:hidden;text-overflow:ellipsis`.
3. **Shortlisted version shows ♪ with no metadata** — Fix: frontend reads cells from browser table row and passes preview metadata in POST body; INSERT stores it immediately.
4. **SW `TypeError: clone on already-used Response`** — Fix: `resp.clone()` called synchronously before async gap.
5. **Thumbnail missing after shortlist (hard refresh fixes it)** — Fix: `_versionThumbs` map stores Discogs CDN thumb at shortlist time; used as fallback until cached image available.
6. **HTTP 500 on wishlist detail Save** — `WishlistUpdateIn` model fixed; staged version changes apply correctly on Save.
7. **HTTP 500 on wantlist preview when shortlisted versions exist** — partial SELECT in `wantlist_preview` didn't include `is_new`; fixed with `SELECT *`.
8. **Page freeze (~60s) after bulk wantlist sync** — `prefetchVersionData()` was firing `/api/release/{id}/info` calls immediately after sync, saturating the browser connection pool with rate-limited Discogs requests. Fixed by removing `prefetchVersionData()` entirely and replacing with `cacheAllVersions()` (DB reads only, no Discogs calls on page load).

### Testing checklist

- [x] Thumbnail fix confirmed working
- [x] Add to collection flow (fulfill → edit modal → wishlist fulfilled prompt)
- [x] Remove version (also removes from Discogs wantlist)
- [x] Notes edit on version
- [x] Wantlist sync preview (sn_only / discogs_only correct)
- [x] Sync to Discogs (in_wantlist=1 in DB, visible in Discogs wantlist)
- [x] Sync from Discogs (master + version created in SN)
- [x] Offline: versions visible from SW cache when server down
- [x] Browse pressings disabled in read-only mode (no internet)
- [x] SW Phase 4: openSwDB() at v3, flushOfflineQueue() covers all five stores

---

## Branch + Version

Branch: `feat/wishlist-versions-v2`
Version bump: `v1.10.0` (minor — new feature)
