#!/usr/bin/env python3
"""
Prepare a live SleeveNotes backup zip for import into the test container.

Replaces discogs_username, discogs_token, and api_key in the embedded SQL
with the values from tests/.env.test, so live credentials never reach the
test Discogs account and the test API key is active after import.

Usage:
    python tests/prepare-backup-for-test.py <input.zip> [output.zip]

If output.zip is omitted, writes <input>-test-ready.zip in the same directory.
"""
import io
import re
import sys
import zipfile
from pathlib import Path
from dotenv import load_dotenv
import os

TESTS_DIR = Path(__file__).parent
load_dotenv(TESTS_DIR / ".env.test")

REPLACEMENTS = {
    "discogs_username": os.getenv("DISCOGS_TEST_USERNAME", ""),
    "discogs_token":    os.getenv("DISCOGS_TEST_TOKEN", ""),
    "api_key":          os.getenv("SN_TEST_API_KEY", ""),
}

_SETTING_RE = re.compile(
    r"(INSERT INTO \"settings\" VALUES\(')([^']+)(',')([^']*)('\);)"
)


def _replace_setting(match: re.Match) -> str:
    key = match.group(2)
    if key in REPLACEMENTS:
        return match.group(1) + key + match.group(3) + REPLACEMENTS[key] + match.group(5)
    return match.group(0)


def prepare(input_path: Path, output_path: Path) -> None:
    with zipfile.ZipFile(input_path, "r") as zin:
        names = zin.namelist()
        sql_names = [n for n in names if n.endswith(".sql")]
        if not sql_names:
            sys.exit(f"No .sql file found in {input_path}")
        if len(sql_names) > 1:
            print(f"Warning: multiple .sql files found, using {sql_names[0]}")
        sql_name = sql_names[0]

        sql = zin.read(sql_name).decode("utf-8")
        patched_sql = _SETTING_RE.sub(_replace_setting, sql)

        changed = {
            k for k in REPLACEMENTS
            if re.search(rf"INSERT INTO \"settings\" VALUES\('{re.escape(k)}','", patched_sql)
        }
        print(f"Patched settings: {', '.join(sorted(changed)) or 'none'}")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for name in names:
                if name == sql_name:
                    zout.writestr(name, patched_sql.encode("utf-8"))
                else:
                    zout.writestr(name, zin.read(name))

    output_path.write_bytes(buf.getvalue())
    print(f"Written: {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    inp = Path(sys.argv[1])
    if not inp.exists():
        sys.exit(f"File not found: {inp}")
    out = Path(sys.argv[2]) if len(sys.argv) >= 3 else inp.with_stem(inp.stem + "-test-ready")
    prepare(inp, out)
