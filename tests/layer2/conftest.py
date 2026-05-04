import os
import time
import subprocess
import httpx
import pytest
from pathlib import Path
from dotenv import load_dotenv

TESTS_DIR = Path(__file__).parent.parent
load_dotenv(TESTS_DIR / ".env.test")

BASE_URL = "http://localhost:2026"
FIXTURES_DIR = TESTS_DIR / "fixtures"

DISCOGS_TEST_USERNAME = os.getenv("DISCOGS_TEST_USERNAME", "")
DISCOGS_TEST_TOKEN = os.getenv("DISCOGS_TEST_TOKEN", "")
SN_TEST_API_KEY = os.getenv("SN_TEST_API_KEY", "")
SN_TEST_ADD_RELEASE_ID = os.getenv("SN_TEST_ADD_RELEASE_ID", "3019857")


@pytest.fixture(scope="session")
def browser_context(browser, browser_context_args):
    """Session-scoped browser context so localStorage persists across all tests.

    pytest-playwright defaults to a new context per test, which resets
    localStorage. Sharing the context simulates real accumulated browser state
    and lets us catch bugs caused by stale or unexpected localStorage values.
    """
    context = browser.new_context(**browser_context_args)
    yield context
    context.close()


@pytest.fixture
def page(browser_context):
    """Fresh page (tab) per test within the shared session context."""
    page = browser_context.new_page()
    yield page
    page.close()


def pytest_addoption(parser):
    parser.addoption(
        "--full-reset",
        action="store_true",
        default=False,
        help=(
            "Destroy and rebuild the test container + volume before running. "
            "Requires interactive confirmation. Leaves the container in a blank-DB state "
            "so first-run tests (1, 2) can exercise the setup flow."
        ),
    )


def api_headers() -> dict:
    h = {}
    if SN_TEST_API_KEY:
        h["X-API-Key"] = SN_TEST_API_KEY
    return h


@pytest.fixture(scope="session", autouse=True)
def maybe_full_reset(request):
    """Destroy and rebuild the test container if --full-reset is passed.

    Runs before configure_test_container so the container is healthy and blank
    when the session fixture tries to load the golden DB.
    Human confirmation is required — this is destructive and irreversible.
    """
    if not request.config.getoption("--full-reset"):
        return

    print(
        "\n\n⚠️  --full-reset will permanently destroy the test container volume.\n"
        "   All data in the test container (port 2026) will be lost.\n"
    )
    with open("/dev/tty", "w") as tty_out:
        tty_out.write("   Type YES to continue, anything else to abort: ")
        tty_out.flush()
    with open("/dev/tty") as tty_in:
        confirm = tty_in.readline().strip()
    if confirm != "YES":
        pytest.exit("Full reset aborted by user.")

    compose_file = str(TESTS_DIR.parent / "compose.yml")
    compose_override = str(TESTS_DIR.parent / "compose.override.yml")
    subprocess.run(
        ["docker", "compose", "-f", compose_file, "-f", compose_override, "down", "-v"],
        check=True,
    )
    subprocess.run(
        ["docker", "compose", "-f", compose_file, "-f", compose_override, "up", "--build", "-d"],
        check=True,
    )

    # Wait up to 60 s for the container to become healthy
    for _ in range(30):
        try:
            r = httpx.get(f"{BASE_URL}/api/health", timeout=3)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(2)

    pytest.exit("Test container did not become healthy within 60 s after full reset.")


@pytest.fixture(scope="session", autouse=True)
def configure_test_container(maybe_full_reset):
    """Load golden DB and credentials into the test container once per session.

    Depends on maybe_full_reset so it always runs after the container is ready.
    Skips (with a warning) if golden.sql does not exist yet — tests 1 and 2
    manage their own state and do not need it.
    """
    golden = FIXTURES_DIR / "golden.sql"
    if not golden.exists():
        import warnings
        warnings.warn(
            "golden.sql not found — tests 101–145 will fail. "
            "Curate the golden DB and export via /api/export/db first.",
            stacklevel=2,
        )
        return
    _load_db(golden)
    _configure_credentials()


def _load_db(db_path: Path):
    import zipfile, io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.write(db_path, "sleevenotes.sql")
    buf.seek(0)
    r = httpx.post(
        f"{BASE_URL}/api/import/db",
        files={"file": ("backup.zip", buf, "application/zip")},
        headers=api_headers(),
        timeout=30,
    )
    r.raise_for_status()


def _configure_credentials():
    with httpx.Client(base_url=BASE_URL, headers=api_headers(), timeout=10) as c:
        if DISCOGS_TEST_USERNAME:
            c.put("/api/settings/discogs_username", json={"value": DISCOGS_TEST_USERNAME})
        if DISCOGS_TEST_TOKEN:
            c.put("/api/settings/discogs_token", json={"value": DISCOGS_TEST_TOKEN})
        if SN_TEST_API_KEY:
            c.put("/api/settings/api_key", json={"value": SN_TEST_API_KEY})


def load_blank_db():
    """Restore the blank (empty, schema-only) DB into the test container."""
    blank = FIXTURES_DIR / "blank.sql"
    if not blank.exists():
        raise FileNotFoundError(f"Blank DB not found at {blank}")
    _load_db(blank)
    # Intentionally does NOT call _configure_credentials — blank state has no key set.


@pytest.fixture(autouse=True)
def restore_golden_db(request):
    """Restore golden DB before every smoke test so each test starts clean.

    Skips for first_run-marked tests — those rely on the blank container state
    left by --full-reset and must not have the golden DB loaded over them.
    Skips silently if golden.sql does not exist yet.
    """
    if request.node.get_closest_marker("first_run"):
        yield
        return
    golden = FIXTURES_DIR / "golden.sql"
    if golden.exists():
        _load_db(golden)
        _configure_credentials()
    yield


@pytest.fixture(autouse=True)
def require_full_reset_for_first_run(request):
    """Skip first_run tests automatically if --full-reset was not passed.

    Without a nuke the container is not in a genuine blank first-run state,
    so these tests would produce meaningless results.
    """
    if request.node.get_closest_marker("first_run"):
        if not request.config.getoption("--full-reset"):
            pytest.skip("first_run tests require --full-reset")
