"""
Layer 2 smoke tests — one test per functional area.

Requires: docker compose -f compose.test.yml up --build -d
Golden DB must exist at tests/fixtures/golden.sql (curated using the test Discogs account).

Test numbering:
  1–99   First-run and setup flow (blank DB, no credentials pre-loaded)
  101–145  Golden DB smoke suite (full collection, credentials configured)
"""
import re
import pytest
from playwright.sync_api import Page, expect

from tests.layer2.conftest import (
    BASE_URL, SN_TEST_API_KEY, SN_TEST_ADD_RELEASE_ID,
    DISCOGS_TEST_USERNAME, DISCOGS_TEST_TOKEN,
)

pytestmark = pytest.mark.smoke

# ── Helpers ───────────────────────────────────────────────────────────────────

def goto(page: Page, path: str = "/"):
    if SN_TEST_API_KEY:
        page.set_extra_http_headers({"X-API-Key": SN_TEST_API_KEY})
    page.goto(f"{BASE_URL}{path}")


# ── 1. First-run — auth setup prompt ─────────────────────────────────────────
# Requires --full-reset (blank container, no API key configured).

@pytest.mark.first_run
def test_first_run_auth_prompt(page: Page):
    page.goto(BASE_URL)
    expect(page.locator("#auth-screen")).to_be_visible()
    # Setup mode: prompts the user to choose a key (not enter an existing one)
    expect(page.locator("#auth-title")).to_have_text("Choose an access key")


# ── 2. First-run — set API key and reach the app ──────────────────────────────
# Requires --full-reset. Sets the API key via the UI and verifies the app loads.

@pytest.mark.first_run
def test_first_run_set_api_key(page: Page):
    page.goto(BASE_URL)
    expect(page.locator("#auth-screen")).to_be_visible()
    page.fill("#auth-key-input", SN_TEST_API_KEY)
    page.click("#auth-submit-btn")
    # After setup, app loads with an empty collection
    expect(page.locator("#stats-bar")).to_be_visible(timeout=10_000)
    expect(page.locator("#main-content")).to_contain_text("Your collection is empty")


# ── 3. First-run — configure Discogs credentials ─────────────────────────────
# Requires --full-reset (follows test 2; API key already set).
# Proves the Discogs connection is working by verifying field mappings load.

@pytest.mark.first_run
def test_first_run_discogs_credentials(page: Page):
    goto(page)
    page.click("#btn-settings")
    expect(page.locator("#modal-settings")).to_be_visible()
    page.fill("#settings-discogs-username", DISCOGS_TEST_USERNAME)
    page.fill("#settings-discogs-token", DISCOGS_TEST_TOKEN)
    page.click("#btn-save-settings")
    # Field mapping section appears once /api/collection/fields returns successfully
    expect(page.locator("#settings-mapping-section")).to_be_visible(timeout=15_000)
    # Error message must not be shown
    expect(page.locator("#settings-mapping-loading")).to_be_hidden()


# ── 4. First-run — configure Discogs field mappings ──────────────────────────
# Requires --full-reset (follows test 3; Discogs credentials already saved).
# Sets all 9 custom field → SN column mappings, saves, reopens and verifies.

FIELD_MAPPINGS = {
    "purchase_date": "4",
    "is_new":        "9",
    "price":         "7",
    "pp":            "6",
    "retailer":      "5",
    "order_ref":     "10",
    "curr_cond":     "1",
    "sleeve_cond":   "2",
    "notes":         "3",
}

@pytest.mark.first_run
def test_first_run_field_mappings(page: Page):
    goto(page)
    page.click("#btn-settings")
    expect(page.locator("#settings-mapping-section")).to_be_visible(timeout=15_000)
    # Set each dropdown
    for db_col, field_id in FIELD_MAPPINGS.items():
        page.locator(f"select[data-db-col='{db_col}']").select_option(field_id)
    page.click("#btn-save-settings")
    # Close and reopen to verify persistence
    page.locator("#modal-settings button", has_text="Close").click()
    expect(page.locator("#modal-settings")).not_to_have_class(re.compile(r"\bopen\b"))
    page.click("#btn-settings")
    expect(page.locator("#settings-mapping-section")).to_be_visible(timeout=15_000)
    for db_col, field_id in FIELD_MAPPINGS.items():
        expect(page.locator(f"select[data-db-col='{db_col}']")).to_have_value(field_id)


# ── 5. Collection home screen loads with golden DB ───────────────────────────

def test_collection_home_loads(page: Page, restore_golden_db):
    goto(page)
    # Collection is the active section by default
    expect(page.locator("#btn-collection")).to_have_class(re.compile(r"\bactive\b"))
    # Add Record button visible
    expect(page.locator("#btn-add-record")).to_be_visible()
    # KPI bar shows real data — s-total must not be the placeholder dash
    expect(page.locator("#s-total")).not_to_have_text("—")
    # Cost and valuation KPIs show currency symbol and a value
    cost_text = page.locator("#s-cost").inner_text()
    assert "£" in cost_text and any(c.isdigit() for c in cost_text)
    val_text = page.locator("#s-valuation").inner_text()
    assert "£" in val_text and any(c.isdigit() for c in val_text)
    # Table has rendered at least one record row from the golden DB
    expect(page.locator("#main-content table tbody tr").first).to_be_visible()


# ── 102. Add record via Discogs lookup ───────────────────────────────────────

def test_add_record(page: Page):
    goto(page)
    page.click("#btn-add-record")
    expect(page.locator("#modal-form")).to_be_visible()
    # Release ID from .env.test (SN_TEST_ADD_RELEASE_ID); defaults to r3019857 (Kind of Blue).
    # Update to a release from the test Discogs account once golden DB is curated.
    page.fill("#f-discogs-id", SN_TEST_ADD_RELEASE_ID)
    page.click("#fetch-btn")
    # Discogs fetch populates fields; wait for artist to appear
    expect(page.locator("#f-artist")).not_to_be_empty(timeout=15_000)
    page.click("#save-btn")
    expect(page.locator("#modal-form")).to_be_hidden()


# ── 6. Tile view renders covers and restores to table ─────────────────────────

def test_collection_tile_view(page: Page):
    goto(page)
    page.click("#btn-tile")
    tiles = page.locator("#main-content .tile")
    expect(tiles.first).to_be_visible()
    expect(tiles.first.locator(".tile-overlay-artist")).to_be_attached()
    # Restore to table view
    page.click("#btn-table")
    expect(page.locator("#main-content table tbody tr").first).to_be_visible()


# ── 7. Tile — overlay then View button opens detail modal ─────────────────────

def test_record_detail_tile(page: Page):
    goto(page)
    page.click("#btn-tile")
    first_tile = page.locator("#main-content .tile").first
    expect(first_tile).to_be_visible()
    first_tile.click()
    # First tap activates tile and shows overlay
    expect(first_tile).to_have_class(re.compile(r"\bactive\b"))
    # Click the View button inside the overlay to open detail modal
    first_tile.locator("button", has_text="View").click()
    expect(page.locator("#modal-detail")).to_be_visible()
    expect(page.locator("#detail-modal-title")).not_to_be_empty()


# ── 8. Column sort cycles asc → desc → cleared ────────────────────────────────

def test_column_sort(page: Page):
    goto(page)
    page.click("#btn-table")
    artist_th = page.locator("th", has_text="Artist")
    artist_th.click()
    expect(artist_th).to_have_class(re.compile(r"\bsorted\b"))
    expect(artist_th.locator(".sort-arrow")).to_have_text("▲")
    artist_th.click()
    expect(artist_th).to_have_class(re.compile(r"\bsorted\b"))
    expect(artist_th.locator(".sort-arrow")).to_have_text("▼")
    artist_th.click()
    expect(artist_th).not_to_have_class(re.compile(r"\bsorted\b"))


# ── 9. Group by artist toggle and restore ─────────────────────────────────────

def test_group_by_artist(page: Page):
    goto(page)
    page.click("#btn-table")
    page.locator("#group-by-wrapper .toggle-track").click()
    expect(page.locator("#main-content .group-header").first).to_be_visible()
    # Restore — click again to toggle off
    page.locator("#group-by-wrapper .toggle-track").click()
    expect(page.locator("#main-content .group-header")).to_have_count(0)


# ── 10. Format filter bar filters the table ───────────────────────────────────

def test_format_filter_bar(page: Page):
    goto(page)
    page.click("#btn-table")
    if not page.locator("#format-filter-bar").is_visible():
        page.locator("#show-tags + .toggle-track").click()
    tags = page.locator("#format-filter-bar .fmt-tag-filter")
    if tags.count() == 0:
        pytest.skip("Golden DB has no format tags — add records with a format to verify")
    first_tag_text = tags.first.inner_text()
    tags.first.click()
    rows = page.locator("#main-content table tbody tr:not(.group-header)")
    for i in range(min(rows.count(), 5)):
        expect(rows.nth(i).locator(".fmt-tag").filter(has_text=first_tag_text)).not_to_have_count(0)


# ── 11. Search bar filters results live ───────────────────────────────────────

def test_search_bar_filters(page: Page):
    goto(page)
    page.click("#btn-table")
    rows_before = page.locator("#main-content table tbody tr").count()
    page.fill("#search", "zzzznorecordmatch")
    expect(page.locator("#main-content table tbody tr")).to_have_count(0)
    page.fill("#search", "")
    expect(page.locator("#main-content table tbody tr")).to_have_count(rows_before)


# ── 12. Surprise Me opens detail modal ───────────────────────────────────────────

def test_surprise_me(page: Page):
    goto(page)
    page.click("#btn-table")
    page.locator("button", has_text="Surprise Me").click()
    expect(page.locator("#modal-detail")).to_be_visible()


# ── 13. Record detail modal — all fields populated (London Grammar) ───────────
# Relies on clean_artists being enabled in the golden DB.

def test_record_detail_fields(page: Page):
    goto(page)
    page.click("#btn-table")
    page.fill("#search", "If You Wait")
    page.locator("#main-content table tbody tr").first.click()
    expect(page.locator("#modal-detail")).to_be_visible()
    expect(page.locator(".detail-artist")).to_contain_text("London Grammar")
    expect(page.locator(".detail-title")).to_contain_text("If You Wait")
    for key in ["Label", "Cat No.", "Year", "Format", "Media", "Sleeve",
                "Retailer", "Purchase Date", "Price", "Valuation", "Notes"]:
        row = page.locator(".detail-row", has=page.locator(".detail-key", has_text=key))
        expect(row.locator(".detail-val")).not_to_have_text("—")
    # Condition: record is New (is_new stored as the string "New")
    condition_row = page.locator(".detail-row", has=page.locator(".detail-key", has_text="Condition"))
    expect(condition_row.locator(".detail-val")).to_have_text("New")
    # Cover image present — class changes once carousel loads so match any img
    expect(page.locator("#detail-cover-wrap img")).to_be_visible(timeout=10_000)
    # Carousel arrows appear after async image fetch
    expect(page.locator("#detail-cover-wrap .carousel-arrow")).not_to_have_count(0, timeout=10_000)


# ── 14. Tracklist tab — tracks and heading rows (Raye) ────────────────────────
# Raye's This Music May Contain Hope has side-break heading rows, which is rare
# and worth asserting explicitly.

def test_tracklist_with_headings(page: Page):
    goto(page)
    page.click("#btn-table")
    page.fill("#search", "This Music May Contain Hope")
    page.locator("#main-content table tbody tr").first.click()
    expect(page.locator("#modal-detail")).to_be_visible()
    page.locator("button.detail-tab-btn", has_text="Tracklist").click()
    # Tracklist loads async — wait for table to appear
    expect(page.locator("#tracklist-content .tracklist-table")).to_be_visible(timeout=10_000)
    # Regular track rows present
    expect(page.locator("#tracklist-content tr:not(.tracklist-heading)").first).to_be_visible()
    # Heading rows (side breaks) present
    expect(page.locator("#tracklist-content .tracklist-heading").first).to_be_visible()


# ── 15. Record modal navigation arrows ────────────────────────────────────────
# Opens Raye without filtering so the full collection is in the nav list.
# Next record in default (id ASC) order is Fleetwood Mac — Rumours.

def test_record_modal_navigation(page: Page):
    goto(page)
    page.click("#btn-table")
    page.locator("#main-content table tbody tr", has_text="This Music May Contain Hope").first.click()
    expect(page.locator("#modal-detail")).to_be_visible()
    expect(page.locator("#detail-modal-title")).to_contain_text("Raye")
    page.click("#detail-next-btn")
    expect(page.locator("#detail-modal-title")).to_contain_text("Fleetwood Mac")


# ── 16. Cover image opens lightbox ────────────────────────────────────────────

def test_cover_image_lightbox(page: Page):
    goto(page)
    page.click("#btn-table")
    page.locator("#main-content table tbody tr", has_text="This Music May Contain Hope").first.click()
    expect(page.locator("#modal-detail")).to_be_visible()
    # Wait for image (carousel may replace initial cover)
    expect(page.locator("#detail-cover-wrap img")).to_be_visible(timeout=10_000)
    page.locator("#detail-cover-wrap img").click()
    expect(page.locator("#lightbox")).to_be_visible()
    expect(page.locator("#lightbox-img")).to_have_attribute("src", re.compile(r"/images/"))


# ── 17. Edit form — Sync Metadata button fires and preview appears ─────────────

def test_sync_metadata(page: Page):
    goto(page)
    page.click("#btn-table")
    page.fill("#search", "This Music May Contain Hope")
    page.locator("#main-content table tbody tr").first.click()
    expect(page.locator("#modal-detail")).to_be_visible()
    page.click("#detail-edit-btn")
    expect(page.locator("#modal-form")).to_be_visible()
    expect(page.locator("#form-modal-title")).to_have_text("Edit Record")
    # In edit mode the fetch button becomes Sync Metadata
    expect(page.locator("#fetch-btn")).to_have_text("Sync Metadata")
    page.click("#fetch-btn")
    # Discogs preview card populates with artist/title from the API response
    expect(page.locator("#discogs-preview")).to_be_visible(timeout=15_000)
    expect(page.locator("#discogs-preview")).to_contain_text("Raye")
    page.locator("#modal-form button", has_text="Cancel").click()


# ── 18. Edit form — Sync Custom Fields opens diff modal ───────────────────────

def test_sync_custom_fields(page: Page):
    goto(page)
    page.click("#btn-table")
    page.fill("#search", "This Music May Contain Hope")
    page.locator("#main-content table tbody tr").first.click()
    expect(page.locator("#modal-detail")).to_be_visible()
    page.click("#detail-edit-btn")
    expect(page.locator("#modal-form")).to_be_visible()
    expect(page.locator("#sync-fields-btn")).to_be_visible()
    page.click("#sync-fields-btn")
    expect(page.locator("#modal-discogs-sync")).to_be_visible(timeout=5_000)
    # Wait for Discogs collection preview to load and diff to render
    expect(page.locator("#sync-preview-content")).to_be_visible(timeout=20_000)
    expect(page.locator("#sync-preview-content")).to_contain_text("Raye")
    page.locator("#modal-discogs-sync button", has_text="Cancel").click()
    page.locator("#modal-form button", has_text="Cancel").click()


# ── 19. Edit record — all 9 purchase/condition fields persist after save ──────

def test_edit_record_fields(page: Page):
    goto(page)
    page.click("#btn-table")
    page.fill("#search", "This Music May Contain Hope")
    page.locator("#main-content table tbody tr").first.click()
    expect(page.locator("#modal-detail")).to_be_visible()
    page.click("#detail-edit-btn")
    expect(page.locator("#modal-form")).to_be_visible()

    page.fill("#f-is-new", "Pre-Owned")
    page.locator("#f-curr-cond").select_option("VG")
    page.locator("#f-sleeve-cond").select_option("VG")
    page.fill("#f-retailer", "Test Shop")
    page.fill("#f-order-ref", "TEST-001")
    page.fill("#f-purchase-date", "2024-06-15")
    page.fill("#f-price", "9.99")
    page.fill("#f-pp", "2.50")
    page.fill("#f-notes", "Test edit notes")

    page.click("#save-btn")
    expect(page.locator("#modal-form")).not_to_have_class(re.compile(r"\bopen\b"))

    # Reopen detail and verify all 9 fields reflect the saved values
    page.locator("#main-content table tbody tr", has_text="This Music May Contain Hope").first.click()
    expect(page.locator("#modal-detail")).to_be_visible()

    def detail_val(key):
        return page.locator(".detail-row", has=page.locator(".detail-key", has_text=key)).locator(".detail-val")

    expect(detail_val("Condition")).to_have_text("Pre-Owned")
    expect(detail_val("Media")).to_have_text("Very Good (VG)")
    expect(detail_val("Sleeve")).to_have_text("Very Good (VG)")
    expect(detail_val("Retailer")).to_have_text("Test Shop")
    expect(detail_val("Order Ref")).to_have_text("TEST-001")
    expect(detail_val("Purchase Date")).to_have_text("15/06/2024")
    expect(detail_val("Price")).to_have_text("£9.99")
    expect(detail_val("P&P")).to_have_text("£2.50")
    expect(detail_val("Notes")).to_have_text("Test edit notes")


# ── 20. Carousel — Use as Cover changes the cover image ───────────────────────

def test_use_as_cover(page: Page):
    goto(page)
    page.click("#btn-table")
    page.locator("#main-content table tbody tr", has_text="This Music May Contain Hope").first.click()
    expect(page.locator("#modal-detail")).to_be_visible()
    # Wait for carousel arrows (multiple images confirmed for this record)
    expect(page.locator("#detail-cover-wrap .carousel-arrow")).not_to_have_count(0, timeout=10_000)
    # Navigate to the next image (not the current cover — Use as Cover will be enabled)
    page.locator("#detail-cover-wrap .carousel-arrow.next").click()
    use_cover_btn = page.locator(".carousel-meta button", has_text="Use as Cover")
    expect(use_cover_btn).to_be_enabled(timeout=5_000)
    use_cover_btn.click()
    # Toast confirms; setCover reloads records and reopens detail
    expect(page.locator("#toasts .toast")).to_contain_text("Cover updated", timeout=10_000)
    # Carousel rebuilds — current image (new cover, index 0) has disabled Use as Cover
    expect(page.locator("#detail-cover-wrap .carousel-arrow")).not_to_have_count(0, timeout=10_000)
    expect(page.locator(".carousel-meta button", has_text="Use as Cover")).to_be_disabled()


# ── 21. Add record via Discogs lookup ────────────────────────────────────────

def test_add_record(page: Page):
    goto(page)
    page.click("#btn-table")
    before = page.locator("#main-content table tbody tr").count()
    page.click("#btn-add-record")
    expect(page.locator("#modal-form")).to_be_visible()
    expect(page.locator("#form-modal-title")).to_have_text("Add Record")
    expect(page.locator("#fetch-btn")).to_have_text("Fetch")
    page.fill("#f-discogs-id", SN_TEST_ADD_RELEASE_ID)
    page.click("#fetch-btn")
    # Discogs fetch populates fields and shows preview card
    expect(page.locator("#f-artist")).not_to_be_empty(timeout=15_000)
    expect(page.locator("#discogs-preview")).to_be_visible()
    page.click("#save-btn")
    expect(page.locator("#modal-form")).not_to_have_class(re.compile(r"\bopen\b"))
    expect(page.locator("#main-content table tbody tr")).to_have_count(before + 1, timeout=10_000)


# ── 22. Delete record ─────────────────────────────────────────────────────────
# Deletes the record added in test 20. Opens it via the edit form where the
# Delete button lives, accepts the confirm dialog, and asserts row count drops.

def test_delete_record(page: Page):
    goto(page)
    page.click("#btn-table")
    before = page.locator("#main-content table tbody tr").count()
    page.locator("#main-content table tbody tr", has_text="Never Gonna Give You Up").first.click()
    expect(page.locator("#modal-detail")).to_be_visible()
    page.click("#detail-edit-btn")
    expect(page.locator("#modal-form")).to_be_visible()
    expect(page.locator("#delete-btn")).to_be_visible()
    page.on("dialog", lambda d: d.accept())
    page.click("#delete-btn")
    expect(page.locator("#modal-form")).not_to_have_class(re.compile(r"\bopen\b"))
    expect(page.locator("#toasts .toast")).to_contain_text("Record deleted", timeout=5_000)
    expect(page.locator("#main-content table tbody tr")).to_have_count(before - 1, timeout=10_000)
