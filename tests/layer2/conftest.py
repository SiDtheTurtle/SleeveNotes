import os
import httpx
import pytest
from pathlib import Path
from dotenv import load_dotenv

TESTS_DIR = Path(__file__).parent.parent
load_dotenv(TESTS_DIR / ".env.test")

BASE_URL = "http://localhost:2027"
FIXTURES_DIR = TESTS_DIR / "fixtures"

DISCOGS_TEST_USERNAME = os.getenv("DISCOGS_TEST_USERNAME", "")
DISCOGS_TEST_TOKEN = os.getenv("DISCOGS_TEST_TOKEN", "")
SN_TEST_API_KEY = os.getenv("SN_TEST_API_KEY", "")


def api_headers() -> dict:
    h = {}
    if SN_TEST_API_KEY:
        h["X-API-Key"] = SN_TEST_API_KEY
    return h


@pytest.fixture(scope="session", autouse=True)
def configure_test_container():
    """Load golden DB and credentials into the test container once per session."""
    golden = FIXTURES_DIR / "golden.db"
    if not golden.exists():
        raise FileNotFoundError(
            f"Golden DB not found at {golden}. "
            "Create it by running the test container, curating data, then exporting via /api/export/db."
        )
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
    blank = FIXTURES_DIR / "blank.db"
    if not blank.exists():
        raise FileNotFoundError(f"Blank DB not found at {blank}")
    _load_db(blank)
    _configure_credentials()


@pytest.fixture(autouse=True)
def restore_golden_db():
    """Restore golden DB before every smoke test so each test starts clean."""
    golden = FIXTURES_DIR / "golden.db"
    _load_db(golden)
    _configure_credentials()
    yield
