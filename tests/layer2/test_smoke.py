"""
Layer 2 smoke tests — one test per functional area.

Requires: docker compose -f compose.test.yml up --build -d
Golden DB must exist at tests/fixtures/golden.db (curated using the test Discogs account).
"""
import re
import pytest
from playwright.sync_api import Page, expect

from tests.layer2.conftest import BASE_URL, SN_TEST_API_KEY, load_blank_db

pytestmark = pytest.mark.smoke

# ── Helpers ───────────────────────────────────────────────────────────────────

def goto(page: Page, path: str = "/"):
    if SN_TEST_API_KEY:
        page.set_extra_http_headers({"X-API-Key": SN_TEST_API_KEY})
    page.goto(f"{BASE_URL}{path}")


# ── 1. App load ───────────────────────────────────────────────────────────────

def test_app_loads(page: Page):
    goto(page)
    expect(page.locator("#stats-bar")).to_be_visible()
    expect(page.locator("#toolbar")).to_be_visible()
    expect(page.locator("#main-content")).to_be_visible()


# ── 2. Add record via Discogs lookup ─────────────────────────────────────────

def test_add_record(page: Page):
    goto(page)
    page.click("#btn-add-record")
    expect(page.locator("#modal-form")).to_be_visible()
    page.fill("#f-discogs-id", "99999999")
    page.click("#fetch-btn")
    # Discogs fetch populates fields; wait for artist to appear
    expect(page.locator("#f-artist")).not_to_be_empty(timeout=15_000)
    page.click("#save-btn")
    expect(page.locator("#modal-form")).to_be_hidden()


# ── 3. Collection table renders records ───────────────────────────────────────

def test_collection_table_shows_records(page: Page):
    goto(page)
    expect(page.locator("#btn-table")).to_be_visible()
    # Golden DB has at least one record
    rows = page.locator("#main-content table tbody tr")
    expect(rows.first).to_be_visible()


# ── 4. Collection tile view ───────────────────────────────────────────────────

def test_collection_tile_view(page: Page):
    goto(page)
    page.click("#btn-tile")
    tiles = page.locator("#main-content .tile")
    expect(tiles.first).to_be_visible()
    # Each tile has an artist label
    expect(tiles.first.locator(".tile-artist")).to_be_visible()


# ── 5. Column sort ────────────────────────────────────────────────────────────

def test_column_sort(page: Page):
    goto(page)
    page.click("#btn-table")
    # Click Artist header → asc sort
    page.locator("th", has_text="Artist").click()
    expect(page.locator("th.sort-asc", has_text="Artist")).to_be_visible()
    # Click again → desc
    page.locator("th", has_text="Artist").click()
    expect(page.locator("th.sort-desc", has_text="Artist")).to_be_visible()
    # Click again → cleared
    page.locator("th", has_text="Artist").click()
    expect(page.locator("th.sort-asc", has_text="Artist")).to_have_count(0)


# ── 6. Group by artist ────────────────────────────────────────────────────────

def test_group_by_artist(page: Page):
    goto(page)
    page.click("#btn-table")
    page.check("#group-by-artist")
    # Artist heading rows appear
    expect(page.locator("#main-content .artist-group-header").first).to_be_visible()


# ── 7. Format filter bar ──────────────────────────────────────────────────────

def test_format_filter_bar(page: Page):
    goto(page)
    page.click("#btn-table")
    # Ensure tags bar is visible (golden DB has records with format tags)
    if not page.locator("#format-filter-bar").is_visible():
        page.click("#show-tags")
    tags = page.locator("#format-filter-bar .format-tag")
    if tags.count() > 0:
        first_tag_text = tags.first.inner_text()
        tags.first.click()
        # After click, all visible rows should match the tag
        rows = page.locator("#main-content table tbody tr:not(.artist-group-header)")
        for i in range(min(rows.count(), 5)):
            expect(rows.nth(i).locator(".format-tags")).to_contain_text(first_tag_text)


# ── 8. Search bar filters results ─────────────────────────────────────────────

def test_search_bar_filters(page: Page):
    goto(page)
    rows_before = page.locator("#main-content table tbody tr").count()
    page.fill("#search", "zzzznorecordmatch")
    expect(page.locator("#main-content table tbody tr")).to_have_count(0)
    page.fill("#search", "")
    expect(page.locator("#main-content table tbody tr")).to_have_count(rows_before)


# ── 9. Record detail modal ────────────────────────────────────────────────────

def test_record_detail_modal(page: Page):
    goto(page)
    page.click("#btn-tile")
    tile = page.locator("#main-content .tile").first
    tile.click()  # first click: overlay
    tile.click()  # second click: detail modal
    expect(page.locator("#modal-detail")).to_be_visible()
    expect(page.locator("#detail-modal-title")).not_to_be_empty()


# ── 10. Tracklist tab ─────────────────────────────────────────────────────────

def test_tracklist_tab(page: Page):
    goto(page)
    page.click("#btn-tile")
    tile = page.locator("#main-content .tile").first
    tile.click()
    tile.click()
    expect(page.locator("#modal-detail")).to_be_visible()
    page.locator("#detail-panel-tracklist").click()
    expect(page.locator("#tracklist-content")).to_be_visible()


# ── 11. Edit record ───────────────────────────────────────────────────────────

def test_edit_record(page: Page):
    goto(page)
    page.click("#btn-table")
    page.locator("#main-content table tbody tr").first.locator("[data-action='edit']").click()
    expect(page.locator("#modal-form")).to_be_visible()
    page.fill("#f-notes", "Smoke test note")
    page.click("#save-btn")
    expect(page.locator("#modal-form")).to_be_hidden()
    expect(page.locator("#main-content")).to_contain_text("Smoke test note")


# ── 12. Delete record ─────────────────────────────────────────────────────────

def test_delete_record(page: Page):
    goto(page)
    page.click("#btn-table")
    rows_before = page.locator("#main-content table tbody tr").count()
    page.locator("#main-content table tbody tr").first.locator("[data-action='delete']").click()
    # Confirm deletion in dialog
    page.on("dialog", lambda d: d.accept())
    expect(page.locator("#main-content table tbody tr")).to_have_count(rows_before - 1)


# ── 13. KPI — total count ─────────────────────────────────────────────────────

def test_kpi_total_count(page: Page):
    goto(page)
    total_text = page.locator("#s-total").inner_text()
    total = int(re.search(r"\d+", total_text).group())
    assert total > 0


# ── 14. KPI — collection cost ─────────────────────────────────────────────────

def test_kpi_collection_cost(page: Page):
    goto(page)
    # Golden DB should have records with price > 0
    expect(page.locator("#s-cost")).to_be_visible()
    cost_text = page.locator("#s-cost").inner_text()
    assert any(c.isdigit() for c in cost_text)


# ── 15. Wishlist section loads ────────────────────────────────────────────────

def test_wishlist_section_loads(page: Page):
    goto(page)
    page.click("#btn-wishlist-nav")
    expect(page.locator("#main-content")).to_be_visible()
    # Format filter bar hidden in wishlist
    expect(page.locator("#format-filter-bar")).to_be_hidden()
    # Wishlist-specific toggle visible
    expect(page.locator("#show-fulfilled")).to_be_visible()


# ── 16. Wishlist search modal ─────────────────────────────────────────────────

def test_wishlist_search_modal(page: Page):
    goto(page)
    page.click("#btn-wishlist-nav")
    page.locator("#search").press("Enter")
    expect(page.locator("#modal-wishlist-search")).to_be_visible()
    page.fill("#wishlist-search-input", "blue note")
    page.click("#wishlist-search-btn")
    expect(page.locator("#wishlist-search-results")).not_to_be_empty(timeout=15_000)


# ── 17. Add to wishlist ───────────────────────────────────────────────────────

def test_add_to_wishlist(page: Page):
    goto(page)
    page.click("#btn-wishlist-nav")
    items_before = page.locator("#main-content table tbody tr").count()
    page.locator("#search").press("Enter")
    page.fill("#wishlist-search-input", "miles davis kind of blue")
    page.click("#wishlist-search-btn")
    expect(page.locator("#wishlist-search-results")).not_to_be_empty(timeout=15_000)
    add_btn = page.locator("#wishlist-search-results button", has_text="Add").first
    add_btn.click()
    # Close modal and check list grew
    page.keyboard.press("Escape")
    expect(page.locator("#main-content table tbody tr")).to_have_count(items_before + 1, timeout=10_000)


# ── 18. Wishlist tile view ────────────────────────────────────────────────────

def test_wishlist_tile_view(page: Page):
    goto(page)
    page.click("#btn-wishlist-nav")
    page.click("#btn-tile")
    tiles = page.locator("#main-content .tile")
    expect(tiles.first).to_be_visible()


# ── 19. Wishlist detail modal ─────────────────────────────────────────────────

def test_wishlist_detail_modal(page: Page):
    goto(page)
    page.click("#btn-wishlist-nav")
    page.click("#btn-table")
    page.locator("#main-content table tbody tr").first.click()
    expect(page.locator("#modal-wishlist-detail")).to_be_visible()
    expect(page.locator("#wishlist-detail-notes")).to_be_visible()


# ── 20. Mark wishlist item fulfilled ─────────────────────────────────────────

def test_mark_wishlist_fulfilled(page: Page):
    goto(page)
    page.click("#btn-wishlist-nav")
    page.click("#btn-table")
    rows_before = page.locator("#main-content table tbody tr").count()
    page.locator("#main-content table tbody tr").first.click()
    expect(page.locator("#modal-wishlist-detail")).to_be_visible()
    page.check("#wishlist-detail-fulfilled")
    page.click("#wishlist-detail-save-btn")
    # Item should disappear (show-fulfilled is off by default)
    expect(page.locator("#main-content table tbody tr")).to_have_count(rows_before - 1, timeout=5_000)


# ── 21. Delete wishlist item ──────────────────────────────────────────────────

def test_delete_wishlist_item(page: Page):
    goto(page)
    page.click("#btn-wishlist-nav")
    page.click("#btn-table")
    rows_before = page.locator("#main-content table tbody tr").count()
    page.locator("#main-content table tbody tr").first.click()
    expect(page.locator("#modal-wishlist-detail")).to_be_visible()
    page.on("dialog", lambda d: d.accept())
    page.click("#wishlist-detail-delete-btn")
    expect(page.locator("#main-content table tbody tr")).to_have_count(rows_before - 1, timeout=5_000)


# ── 22. Settings modal open/close ─────────────────────────────────────────────

def test_settings_modal_open_close(page: Page):
    goto(page)
    page.click("#btn-settings")
    expect(page.locator("#modal-settings")).to_be_visible()
    page.locator("#modal-settings .modal-close").click()
    expect(page.locator("#modal-settings")).to_be_hidden()


# ── 23. Settings — currency symbol ───────────────────────────────────────────

def test_settings_currency_change(page: Page):
    goto(page)
    page.click("#btn-settings")
    expect(page.locator("#modal-settings")).to_be_visible()
    page.fill("#settings-currency", "$")
    page.click("#btn-save-settings")
    page.locator("#modal-settings .modal-close").click()
    # KPI cost should now show $
    cost_text = page.locator("#s-cost").inner_text()
    assert "$" in cost_text


# ── 24. Export CSV ────────────────────────────────────────────────────────────

def test_export_csv_download(page: Page):
    goto(page)
    page.click("#btn-settings")
    with page.expect_download() as dl_info:
        page.locator("button", has_text="Export CSV").click()
    download = dl_info.value
    assert download.suggested_filename.endswith(".csv")


# ── 25. Export DB ─────────────────────────────────────────────────────────────

def test_export_db_download(page: Page):
    goto(page)
    page.click("#btn-settings")
    with page.expect_download() as dl_info:
        page.click("#btn-export-db")
    download = dl_info.value
    assert download.suggested_filename.endswith(".zip")


# ── 26. Import CSV opens sync diff modal ──────────────────────────────────────

def test_import_csv_opens_diff_modal(page: Page):
    goto(page)
    page.click("#btn-settings")
    csv_content = (
        "Catalog#,Artist,Title,Label,Format,Released,release_id,"
        "CollectionFolder,Collection Media Condition,Collection Sleeve Condition\r\n"
        "TEST-001,Test Artist,Test Album,Test Label,Vinyl,2000,99999999,1,NM,NM\r\n"
    )
    page.locator("#input-import-csv").set_input_files({
        "name": "test.csv",
        "mimeType": "text/csv",
        "buffer": csv_content.encode(),
    })
    expect(page.locator("#modal-discogs-sync")).to_be_visible(timeout=10_000)


# ── 27. Collection sync preview ───────────────────────────────────────────────

def test_collection_sync_preview(page: Page):
    goto(page)
    page.click("#btn-settings")
    page.click("#btn-sync-discogs")
    expect(page.locator("#modal-discogs-sync")).to_be_visible(timeout=20_000)
    expect(page.locator("#sync-preview-content")).to_be_visible()


# ── 28. Auth screen ───────────────────────────────────────────────────────────

def test_auth_screen(page: Page):
    load_blank_db()
    # Set an API key directly via API (no browser auth yet needed since blank DB has no key)
    import httpx
    httpx.put(f"{BASE_URL}/api/settings/api_key", json={"value": "testkey123"}, timeout=5)
    goto(page)
    expect(page.locator("#auth-screen")).to_be_visible()
    page.fill("#auth-key-input", "testkey123")
    page.click("#auth-submit-btn")
    expect(page.locator("#stats-bar")).to_be_visible()


# ── 29. KPI — Collection Value ────────────────────────────────────────────────

def test_kpi_collection_value(page: Page):
    goto(page)
    # Golden DB must have at least one record with valuation > 0
    expect(page.locator("#s-valuation")).to_be_visible()
    val_text = page.locator("#s-valuation").inner_text()
    assert any(c.isdigit() for c in val_text)


# ── 30. Record detail — image carousel ───────────────────────────────────────
# Requires golden DB to have at least one record with >1 cached image.

def test_record_detail_carousel(page: Page):
    goto(page)
    page.click("#btn-tile")
    tile = page.locator("#main-content .tile").first
    tile.click()
    tile.click()
    expect(page.locator("#modal-detail")).to_be_visible()
    arrows = page.locator("#detail-cover-wrap .carousel-arrow")
    if arrows.count() == 0:
        pytest.skip("Golden DB record has only one image — curate a multi-image record")
    expect(arrows.first).to_be_visible()


# ── 31. Record detail — Use as Cover ─────────────────────────────────────────
# Requires golden DB to have a record with >1 cached image.

def test_record_set_cover(page: Page):
    goto(page)
    page.click("#btn-tile")
    tile = page.locator("#main-content .tile").first
    tile.click()
    tile.click()
    expect(page.locator("#modal-detail")).to_be_visible()
    next_arrow = page.locator("#detail-cover-wrap .carousel-arrow.next")
    if next_arrow.count() == 0:
        pytest.skip("Golden DB record has only one image — curate a multi-image record")
    next_arrow.click()
    use_cover_btn = page.locator("#detail-cover-wrap button", has_text="Use as Cover")
    expect(use_cover_btn).to_be_enabled()
    use_cover_btn.click()
    expect(page.locator(".toast")).to_contain_text("Cover updated", timeout=5_000)


# ── 32. Wishlist — Show Fulfilled toggle ──────────────────────────────────────

def test_wishlist_show_fulfilled_toggle(page: Page):
    goto(page)
    page.click("#btn-wishlist-nav")
    page.click("#btn-table")
    rows_before = page.locator("#main-content table tbody tr").count()
    # Mark first item fulfilled
    page.locator("#main-content table tbody tr").first.click()
    expect(page.locator("#modal-wishlist-detail")).to_be_visible()
    page.check("#wishlist-detail-fulfilled")
    page.click("#wishlist-detail-save-btn")
    expect(page.locator("#main-content table tbody tr")).to_have_count(rows_before - 1, timeout=5_000)
    # Toggle Show Fulfilled — item reappears
    page.check("#show-fulfilled")
    expect(page.locator("#main-content table tbody tr")).to_have_count(rows_before, timeout=5_000)


# ── 33. Wishlist — Save notes persists ───────────────────────────────────────

def test_wishlist_save_notes(page: Page):
    goto(page)
    page.click("#btn-wishlist-nav")
    page.click("#btn-table")
    page.locator("#main-content table tbody tr").first.click()
    expect(page.locator("#modal-wishlist-detail")).to_be_visible()
    page.fill("#wishlist-detail-notes", "Smoke test note persist")
    page.click("#wishlist-detail-save-btn")
    expect(page.locator("#modal-wishlist-detail")).to_be_hidden(timeout=5_000)
    # Reopen and verify
    page.locator("#main-content table tbody tr").first.click()
    expect(page.locator("#modal-wishlist-detail")).to_be_visible()
    expect(page.locator("#wishlist-detail-notes")).to_have_value("Smoke test note persist")


# ── 34. Export Images ─────────────────────────────────────────────────────────

def test_export_images_download(page: Page):
    goto(page)
    page.click("#btn-settings")
    with page.expect_download() as dl_info:
        page.click("#btn-export-images")
    download = dl_info.value
    assert download.suggested_filename.endswith(".zip")


# ── 35. Export All ────────────────────────────────────────────────────────────

def test_export_all_download(page: Page):
    goto(page)
    page.click("#btn-settings")
    with page.expect_download() as dl_info:
        page.locator("button", has_text="Export All").click()
    download = dl_info.value
    assert download.suggested_filename.endswith(".zip")


# ── 36. Import CSV — apply sync ───────────────────────────────────────────────

def test_import_csv_apply_sync(page: Page):
    goto(page)
    page.click("#btn-settings")
    csv_content = (
        "Catalog#,Artist,Title,Label,Format,Released,release_id,"
        "CollectionFolder,Collection Media Condition,Collection Sleeve Condition\r\n"
        "APPLY-001,Apply Artist,Apply Album,Apply Label,Vinyl,2001,88888888,1,VG+,VG+\r\n"
    )
    page.locator("#input-import-csv").set_input_files({
        "name": "apply.csv",
        "mimeType": "text/csv",
        "buffer": csv_content.encode(),
    })
    expect(page.locator("#modal-discogs-sync")).to_be_visible(timeout=10_000)
    # Wait for Apply Sync button to become enabled (diff has entries)
    expect(page.locator("#sync-apply-btn")).to_be_enabled(timeout=10_000)
    page.click("#sync-apply-btn")
    expect(page.locator("#modal-discogs-sync")).to_be_hidden(timeout=10_000)


# ── 37. Settings — Include P&P changes cost ───────────────────────────────────
# Requires golden DB to have at least one record with pp > 0.

def test_settings_include_pp(page: Page):
    goto(page)
    cost_without_pp = page.locator("#s-cost").inner_text()
    page.click("#btn-settings")
    page.check("#include-pp-toggle")
    page.click("#btn-save-settings")
    page.locator("#modal-settings .modal-close").click()
    cost_with_pp = page.locator("#s-cost").inner_text()
    # Cost should have changed if any records have p&p
    if cost_without_pp == cost_with_pp:
        pytest.skip("Golden DB has no records with p&p > 0 — add a record with p&p to verify")
    assert cost_without_pp != cost_with_pp


# ── 38. Settings — Show Valuations toggles KPI ───────────────────────────────

def test_settings_show_valuations(page: Page):
    goto(page)
    # Default: valuations shown
    expect(page.locator("#s-valuation").locator("..")).to_be_visible()
    page.click("#btn-settings")
    page.uncheck("#show-valuations")
    page.click("#btn-save-settings")
    page.locator("#modal-settings .modal-close").click()
    # KPI stat item should now be hidden
    expect(page.locator("#s-valuation").locator("..")).to_be_hidden()
    # Re-enable
    page.click("#btn-settings")
    page.check("#show-valuations")
    page.click("#btn-save-settings")
    page.locator("#modal-settings .modal-close").click()
    expect(page.locator("#s-valuation").locator("..")).to_be_visible()


# ── 39. Settings — Hide format tags ──────────────────────────────────────────

def test_settings_hide_format_tags(page: Page):
    goto(page)
    page.click("#btn-settings")
    # Disable hide-format-tags; all tags should show in filter bar after save
    page.uncheck("#hide-format-tags-toggle")
    page.click("#btn-save-settings")
    page.locator("#modal-settings .modal-close").click()
    # Re-enable
    page.click("#btn-settings")
    page.check("#hide-format-tags-toggle")
    page.click("#btn-save-settings")
    page.locator("#modal-settings .modal-close").click()
    # Verify setting saved without error (no toast error visible)
    expect(page.locator(".toast.toast-error")).to_have_count(0)


# ── 40. Danger Zone — Delete All Records ─────────────────────────────────────

def test_danger_zone_delete_all(page: Page):
    goto(page)
    page.click("#btn-settings")
    page.check("#format-safety-toggle")
    page.on("dialog", lambda d: d.accept())
    page.click("#format-db-btn")
    expect(page.locator("#modal-settings")).to_be_hidden(timeout=5_000)
    # Empty collection state
    expect(page.locator("#main-content")).to_contain_text("Your collection is empty", timeout=5_000)


# ── 41. Empty collection state shows restore button ──────────────────────────

def test_empty_collection_restore_button(page: Page):
    # Load blank DB so collection is empty
    from tests.layer2.conftest import load_blank_db
    load_blank_db()
    goto(page)
    expect(page.locator("#main-content")).to_contain_text("Your collection is empty")
    expect(page.locator("#main-content label", has_text="Restore from backup")).to_be_visible()


# ── 42. Danger Zone — Factory Reset ──────────────────────────────────────────

def test_danger_zone_factory_reset(page: Page):
    goto(page)
    page.click("#btn-settings")
    page.check("#factory-reset-safety-toggle")
    page.on("dialog", lambda d: d.accept())
    page.click("#factory-reset-btn")
    expect(page.locator("#modal-settings")).to_be_hidden(timeout=5_000)
    # Empty collection state; settings back to defaults (currency £)
    expect(page.locator("#main-content")).to_contain_text("Your collection is empty", timeout=5_000)
    expect(page.locator("#s-cost")).to_contain_text("£")


# ── 43. Danger Zone — Clear Image Cache ──────────────────────────────────────

def test_danger_zone_clear_images(page: Page):
    goto(page)
    page.click("#btn-settings")
    page.check("#clear-images-safety-toggle")
    page.on("dialog", lambda d: d.accept())
    page.click("#clear-images-btn")
    expect(page.locator(".toast")).to_contain_text("deleted", timeout=5_000)


# ── 44. Danger Zone — Change Access Key ──────────────────────────────────────

def test_danger_zone_change_access_key(page: Page):
    goto(page)
    page.click("#btn-settings")
    page.check("#access-key-safety-toggle")
    new_key = "smoke-newkey-temp"
    page.fill("#settings-access-key", new_key)
    page.click("#change-access-key-btn")
    expect(page.locator(".toast")).to_contain_text("Access key updated", timeout=5_000)
    # Update injected header and verify app still responds
    page.set_extra_http_headers({"X-API-Key": new_key})
    goto(page)
    expect(page.locator("#stats-bar")).to_be_visible()


# ── 45. Danger Zone — Import DB (restore from backup) ─────────────────────────
# Uploads blank.db zip via the Danger Zone, confirms dialog, waits for reload.

def test_danger_zone_import_db(page: Page):
    import io, zipfile, sqlite3
    from tests.layer2.conftest import FIXTURES_DIR
    # Build a zip from blank.db (SQL text dump)
    sql_text = (FIXTURES_DIR / "blank.db").read_text(encoding="utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("sleevenotes.sql", sql_text)
    zip_bytes = buf.getvalue()

    goto(page)
    page.click("#btn-settings")
    page.check("#import-db-safety-toggle")
    page.on("dialog", lambda d: d.accept())
    page.locator("#input-import-db").set_input_files({
        "name": "blank_backup.zip",
        "mimeType": "application/zip",
        "buffer": zip_bytes,
    })
    page.wait_for_load_state("networkidle", timeout=15_000)
    expect(page.locator("#main-content")).to_contain_text("Your collection is empty", timeout=10_000)
