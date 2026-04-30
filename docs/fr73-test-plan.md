# FR #73 — Wishlist Versions + Wantlist Sync: Test Plan

Branch: `feat/wishlist-versions-v2`

---

## How to use this plan

Work through each section in order. Each test case has:
- **Setup** — preconditions
- **Steps** — what to do
- **Expected** — what should happen
- **Pass/Fail**

Run on a clean DB restore before starting. Have Discogs credentials configured in Settings.

---

## Known Bugs (must fix before merge)

### BUG-1 — Version and wishlist cover thumbnails not cached for offline use

**Symptom:** Version thumbnails and wishlist cover images show as broken when offline if the image was not loaded while online in the same SW cache session.

**Root cause:** SW caches `/images/*` cache-first, but only on first load. `loading="lazy"` means off-screen images are never requested and never enter the SW cache. Version thumbnails are especially affected — the versions panel is only opened on demand, so images are never pre-cached. The `_versionThumbs` CDN fallback is in-memory only and lost on page reload.

**Fix needed:** `prefetchVersionData()` (or a dedicated image prefetch pass) should eagerly fetch and cache version cover images after background refresh completes. Wishlist item covers should also be prefetched on load rather than relying on lazy loading to warm the cache.

---

## 1. Data Integrity

### 1.1 — Wishlist versions don't appear in collection

**Steps:** Open Collection view (Table and Tile). Check DB: `SELECT * FROM records WHERE is_wishlist = 1`.

**Expected:** Any shortlisted versions are present in the DB but do NOT appear in the collection table or tile grid.

- [x] Pass

### 1.2 — Unique constraint prevents duplicate shortlisting

**Steps:** Shortlist the same pressing twice (open the same wishlist item, browse pressings, add a version, close, reopen, try to add the same version again).

**Expected:** Second shortlist attempt returns 409 / is silently ignored. Only one row exists in DB for that `(wishlist_id, discogs_id)` combination.

- [x] Pass

### 1.3 — Soft delete doesn't break unique index

**Steps:** Shortlist a version, remove it, then shortlist the same version again.

**Expected:** Re-shortlisting works — the old row has `deleted_at` set, the new row is a fresh insert with `deleted_at = NULL`. Both exist in the DB; only the new one is active.

- [x] Pass

### 1.4 — Collection records unaffected

**Steps:** After shortlisting versions, verify existing collection records are unchanged. Add a new collection record normally.

**Expected:** `GET /api/records` returns no wishlist versions. Adding a record works as before.

- [x] Pass

---

## 2. Shortlisting Versions (Browse Pressings)

### 2.1 — Open version browser

**Setup:** Open a wishlist item detail modal.

**Steps:** Click "Browse pressings" button.

**Expected:** Version browser modal opens, shows pressing results from Discogs (year, country, label, cat no, format). No ♪ placeholder for rows with thumbnails.

- [x] Pass

### 2.2 — Cascading filters

**Steps:** In the version browser, apply a Year filter. Then apply a Country filter.

**Expected:** Each filter narrows results. The options available in each dropdown are derived from releases matching all other active filters (i.e. Country options reflect only the years remaining after Year filter is applied).

- [x] Pass

### 2.3 — Format tags respect Hide Format Tags setting

**Steps:** Enable "Hide format tags" in Settings (e.g. hide "LP, Album"). Open version browser.

**Expected:** Hidden format tags are stripped from the Format column in the version browser.

- [x] Pass

### 2.4 — Shortlist a version (staged)

**Steps:** In the version browser, click "Shortlist" on a pressing. Close the browser. **Do not press Save yet.**

**Expected:** Version appears in the wishlist detail panel with a pending indicator (staged, not yet saved). No DB write has occurred yet — verify via DB or by refreshing the page and reopening the item.

- [x] Pass

### 2.5 — Save staged shortlist

**Steps:** After staging a shortlist (2.4), press Save in the wishlist detail modal.

**Expected:**
- Version is written to DB (`is_wishlist=1`, `wishlist_id` set, `deleted_at=NULL`)
- Version appears in the versions panel immediately with preview metadata (title, label, cat no, year, format, country)
- Thumbnail shows (either cached image or CDN fallback from `_versionThumbs`)
- Background refresh fires — after ~10-30s, full metadata populates (cover image, identifiers, discogs_notes)
- `in_wantlist=0` initially; synced to Discogs via wantlist sync, not automatically

- [x] Pass

### 2.6 — Remove a staged shortlist before saving

**Steps:** Stage a shortlist, then click Remove on the same version in the panel before pressing Save.

**Expected:** Version is removed from staged changes. Pressing Save does nothing for that version. DB unchanged.

- [x] Pass

### 2.7 — Remove a saved version

**Steps:** Open a wishlist item that has a saved shortlisted version. Click Remove on it. Press Save.

**Expected:**
- Version soft-deleted in DB (`deleted_at` set)
- Version removed from versions panel

- [x] Pass

### 2.8 — Thumbnail fallback

**Steps:** Shortlist a version. Immediately (before background refresh completes) look at the versions panel.

**Expected:** Thumbnail shows the Discogs CDN image from the browser table row (not a ♪ placeholder), even before the background image download completes.

- [x] Pass

### 2.9 — "Shortlisted versions (n)" header

**Steps:** Shortlist multiple versions for one wishlist item.

**Expected:** Header in versions panel reads "Shortlisted versions (n)" with correct count.

- [x] Pass

---

## 3. Version Detail & Notes

### 3.1 — Show more details expander (wishlist panel)

**Setup:** A shortlisted version whose background refresh has completed (`identifiers` populated in DB).

**Steps:** Click "Show more details…" on a version in the wishlist detail panel.

**Expected:** Expander shows `discogs_notes` (Discogs prose notes if any) and identifiers (barcodes, matrix numbers). No Discogs API call is made — verify via docker logs showing no new Discogs requests.

- [x] Pass

### 3.2 — Show more details expander (version browser)

**Steps:** In the version browser, click "Details" on a pressing.

**Expected:** Fetches release info (via server when online, directly from Discogs when server down). Shows identifiers and notes.

- [x] Pass

### 3.3 — Thumbnail lightbox

**Steps:** Click a version thumbnail image in the wishlist detail panel.

**Expected:** Lightbox opens showing the full-size cover image.

- [x] Pass

### 3.4 — Edit version notes

**N/A** — Version notes UI dropped as vestigial. Fulfilled versions become collection records and use collection record notes.

### 3.5 — Notes not pushed to Discogs

**N/A** — See 3.4.

---

## 4. Fulfill Version → Add to Collection

### 4.1 — Fulfill flow opens edit modal

**Steps:** Open a wishlist item with a shortlisted version. Click "Add to collection" on a version. Confirm in the dialog.

**Expected:**
- Wishlist detail modal closes
- Edit record modal opens pre-filled with the version's Discogs metadata (artist, title, label, cat no, year, format)
- Discogs ID is populated
- Fetch preview strip shows without pressing Fetch

- [x] Pass

### 4.2 — Wishlist fulfilled prompt fires

**Steps:** Complete the fulfill flow (4.1) and save the record.

**Expected:** Prompt asks whether to mark the parent wishlist item as fulfilled. Accepting marks the wishlist item `fulfilled=1`. Wishlist notes appended to record notes silently (no separate prompt).

- [x] Pass

### 4.3 — Fulfilled version moves to collection

**Steps:** Complete the fulfill flow and confirm fulfilled. Check collection and wishlist.

**Expected:**
- Record appears in Collection with `is_wishlist=0`, `wishlist_id=NULL`
- Record does NOT appear under that wishlist item's versions
- Wishlist item shows as fulfilled (hidden unless "Show fulfilled" is on)

- [x] Pass

### 4.4 — Multiple versions: fulfill one, others remain

**Steps:** Shortlist 2 versions for one wishlist item. Fulfill one.

**Expected:** The fulfilled version moves to collection. The other version remains shortlisted under the wishlist item.

- [x] Pass

---

## 5. Syncing Badges & Cache

### 5.1 — "Syncing…" badge appears after wantlist sync

**Steps:** Do a Discogs → SN wantlist sync that imports new items. Immediately check the wishlist view (tile and table).

**Expected:** Newly imported items show a blue "Syncing…" badge while background refresh is in flight. Badge is on tile top-left; inline in title column in table view.

- [x] Pass

### 5.2 — Badge disappears after refresh

**Steps:** After background refresh completes (wait ~30-60s), refresh the page.

**Expected:** "Syncing…" badges are gone. Version details are fully populated.

- [x] Pass

### 5.3 — No Discogs calls on page load

**Steps:** Hard refresh the page. Watch docker logs.

**Expected:** No calls to `api.discogs.com` in the logs during or after page load. Only `/api/wishlist`, `/api/records`, `/api/settings`, and `/api/wishlist/{id}/versions` calls appear.

- [x] Pass

### 5.4 — `cacheAllVersions` fires on load

**Steps:** Open wishlist section after page load. Check docker logs.

**Expected:** Logs show `GET /api/wishlist/{id}/versions` for each wishlist item (DB reads, fast). All return 200.

- [x] Pass

---

## 6. Wantlist Sync (Settings → Discogs)

### 6.1 — Preview loads correctly

**Steps:** Settings → Discogs → "Sync Discogs wantlist…"

**Expected:** Modal opens, shows loading state, then renders:
- "New from Discogs (N)" section (green header) — items in Discogs wantlist not in SN
- "Only in SleeveNotes (N)" section (blue header) — shortlisted versions not yet in Discogs wantlist
- "N items already in sync" count if applicable
- "Sync (N)" button with correct total count

- [x] Pass

### 6.2 — Checkbox selection updates button count

**Steps:** In the wantlist sync preview, uncheck some items.

**Expected:** "Sync (N)" button count updates live as checkboxes are toggled.

- [x] Pass

### 6.3 — Sync SN → Discogs

**Setup:** Have a shortlisted version with `in_wantlist=0` (not yet synced to Discogs).

**Steps:** Open wantlist sync, check the item in "Only in SleeveNotes", click Sync.

**Expected:**
- Item is added to Discogs wantlist (verify on Discogs.com)
- `in_wantlist=1` in DB for that record
- Toast: "Synced: 1 exported, 0 imported"

- [x] Pass

### 6.4 — Sync Discogs → SN

**Setup:** Have items in Discogs wantlist that are not shortlisted in SN.

**Steps:** Open wantlist sync, check items in "New from Discogs", click Sync.

**Expected:**
- Wishlist master created in SN if not already present (with cover image)
- Version record created (`is_wishlist=1`, `in_wantlist=1`, `discogs_notes` populated from Discogs notes)
- Background refresh fires for each new version
- Toast: "Synced: 0 exported, N imported"
- Page doesn't freeze — no Discogs API calls from the frontend after sync completes

- [x] Pass

### 6.5 — Already in sync items not duplicated

**Steps:** Run wantlist sync twice.

**Expected:** Second preview shows 0 new items in both directions. "N already in sync" count is correct. Sync button is disabled.

- [x] Pass

### 6.6 — Discogs wantlist item with master_id=0

**Setup:** Have a Discogs wantlist item where the release has no master (master_id=0).

**Steps:** Open wantlist sync preview.

**Expected:** Item is either skipped gracefully or handled without a 500 error. No crash.

- [-] Skipped — edge case, no test data available.

---

## 7. Auto-sync to Discogs Wantlist

**Dropped** — auto-sync on shortlist/remove was intentionally removed. Wantlist sync is manual only (Settings → Discogs → "Sync Discogs wantlist…"). See section 6.

---

## 8. Offline — Server Down (Slate banner)

*Simulate by stopping the container: `docker stop sleevenotes`. Browser must be online.*

### 8.1 — Versions panel loads from SW cache

**Steps:** Open a wishlist item whose versions were loaded during the last online session.

**Expected:** Versions panel populates from SW cache. Data matches what was last fetched.

- [x] Pass

### 8.2 — Browse pressings works (hits Discogs directly)

**Steps:** With server down, click "Browse pressings".

**Expected:** Version browser opens and loads results via direct Discogs API call (unauthenticated, page 1 only). Results may be fewer than online (no pagination). Details button also works via direct Discogs call.

- [x] Pass

### 8.3 — Shortlist queued to IDB

**Steps:** With server down, stage a shortlist and save.

**Expected:** Version queued in IDB `version_queue`. Pending item visible in versions panel with appropriate indicator.

- [x] Pass

**Known bug:** Thumbnails for DB-saved versions are broken when offline if the image wasn't loaded while online (SW cache-first path only caches `/images/*` after first load). `_versionThumbs` CDN fallback is in-memory only and lost on page reload.

### 8.4 — Remove queued to IDB

**Steps:** With server down, remove a shortlisted version.

**Expected:** Remove queued in IDB `version_removes`.

- [x] Pass

### 8.5 — Flush on reconnect

**Steps:** Restart the container (`docker start sleevenotes`). Wait for reconnect detection.

**Expected:** Toast confirms queued items flushed. DB reflects the queued operations. `version_queue` and `version_removes` stores are empty.

- [x] Pass

---

## 9. Read-Only Mode — No Internet

*Simulate by disabling network on device (Wi-Fi/ethernet off). Amber banner shown.*

### 9.1 — Versions visible from SW cache

**Steps:** Go offline. Open wishlist items.

**Expected:** Versions panel loads from SW cache for items previously visited online.

- [x] Pass

### 9.2 — Browse pressings disabled

**Steps:** Offline. Try to open version browser.

**Expected:** Button disabled. No attempt to contact Discogs or server.

- [x] Pass

### 9.3 — Shortlist/remove disabled

**Steps:** Offline. Check versions panel controls.

**Expected:** Shortlist and remove controls are disabled or hidden. Remove from wishlist queues to IDB and flushes on reconnect.

- [x] Pass

---

## 10. General Wishlist Behaviour (Regression)

### 10.1 — Add to wishlist (online)

**Steps:** Search for a master release, add it to wishlist.

**Expected:** Appears in wishlist list and tile views with cover. Notes field empty.

- [ ] Pass / Fail

### 10.2 — Edit wishlist item notes and fulfilled

**Steps:** Open a wishlist item, edit notes, toggle fulfilled, Save.

**Expected:** Changes persisted. Fulfilled item hidden unless "Show fulfilled" is on.

- [ ] Pass / Fail

### 10.3 — Delete wishlist item

**Steps:** Open a wishlist item, click "Remove from wishlist", confirm.

**Expected:** Item removed from wishlist and any associated shortlisted versions also cleaned up (verify in DB).

- [ ] Pass / Fail

### 10.4 — Wishlist tile and table views

**Steps:** Switch between Table and Tile views in wishlist section.

**Expected:** Both views render correctly. Pending and Syncing badges appear in both.

- [ ] Pass / Fail

### 10.5 — Show fulfilled toggle

**Steps:** Toggle "Show fulfilled" in the toolbar.

**Expected:** Fulfilled wishlist items appear/disappear correctly. State persists across page refresh.

- [ ] Pass / Fail

### 10.6 — Collection unaffected

**Steps:** After all above testing, check the Collection view (table and tile). Add, edit, and delete a collection record.

**Expected:** No regressions. Collection sync, Discogs lookup, and all collection features work as before.

- [ ] Pass / Fail

---

## 11. Settings Buttons

### 11.1 — Button labels

**Steps:** Open Settings → Discogs section.

**Expected:** Buttons read "Sync Discogs collection…" and "Sync Discogs wantlist…".

- [ ] Pass / Fail

### 11.2 — Sync Discogs collection still works

**Steps:** Run "Sync Discogs collection…" with a fresh DB (or known diff).

**Expected:** Collection sync preview and apply work as before. No regressions from FR #73 changes.

- [ ] Pass / Fail

---

## 12. Import / Export

### 12.1 — Export CSV excludes wishlist versions

**Steps:** Settings → Data → Export CSV. Open the file.

**Expected:** No rows with `is_wishlist=1` data. Only collection records present.

- [ ] Pass / Fail

### 12.2 — Export DB (zip) includes wishlist versions

**Steps:** Settings → Data → Export Database. Unzip and inspect the SQL dump.

**Expected:** `records` table dump includes `is_wishlist=1` rows. Full backup — nothing excluded.

- [ ] Pass / Fail

### 12.3 — Import DB (zip) preserves wishlist versions

**Steps:** Take a DB export (12.2), then restore it via Settings → Danger Zone → Import Database.

**Expected:** After restore, wishlist versions are present in DB. Collection view shows no wishlist versions. Wishlist detail panels show correct shortlisted versions.

- [ ] Pass / Fail

### 12.4 — Collection sync clean after import

**Steps:** After a DB restore (12.3), run "Sync Discogs collection…".

**Expected:** Wishlist versions do not appear in the sync diff. No false "only in Discogs" entries.

- [ ] Pass / Fail

---

## Sign-off

All items passing → update CLAUDE.md testing checklist, merge to main, cut v1.10.0.
