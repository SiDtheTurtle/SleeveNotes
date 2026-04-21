import io
import csv
import json
import re
import sqlite3
import asyncio
import logging
import httpx
from pathlib import Path
from datetime import datetime
from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sleevenotes")

DATA_DIR = Path("/data")
DB_PATH = DATA_DIR / "sleevenotes.db"
IMAGES_DIR = DATA_DIR / "images"

# ── Discogs rate limiter ──────────────────────────────────────────────────────
# Single process-wide broker: all Discogs API calls acquire a slot here.
# Cap at 55/min (buffer under the 60/min Discogs limit).

_discogs_lock = asyncio.Lock()
_discogs_call_times: list[float] = []
_DISCOGS_MAX_PER_MIN = 55


async def _discogs_acquire() -> None:
    """Block until a Discogs API slot is available."""
    global _discogs_call_times
    async with _discogs_lock:
        loop = asyncio.get_running_loop()
        now = loop.time()
        cutoff = now - 60.0
        _discogs_call_times = [t for t in _discogs_call_times if t > cutoff]
        if len(_discogs_call_times) >= _DISCOGS_MAX_PER_MIN:
            wait = (_discogs_call_times[0] - cutoff) + 0.05
            log.debug("Discogs rate limit: waiting %.2fs", wait)
            await asyncio.sleep(wait)
            now = loop.time()
            cutoff = now - 60.0
            _discogs_call_times = [t for t in _discogs_call_times if t > cutoff]
        _discogs_call_times.append(loop.time())


async def discogs_get(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    await _discogs_acquire()
    resp = await client.get(url, **kwargs)
    if resp.status_code == 429:
        log.warning("Discogs 429 on GET %s — waiting 60s then retrying", url)
        await asyncio.sleep(60)
        await _discogs_acquire()
        resp = await client.get(url, **kwargs)
    return resp


async def discogs_post(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    await _discogs_acquire()
    resp = await client.post(url, **kwargs)
    if resp.status_code == 429:
        log.warning("Discogs 429 on POST %s — waiting 60s then retrying", url)
        await asyncio.sleep(60)
        await _discogs_acquire()
        resp = await client.post(url, **kwargs)
    return resp


app = FastAPI(title="SleeveNotes")

def get_discogs_headers() -> dict:
    token = ""
    try:
        with get_db() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key='discogs_token'").fetchone()
            if row and row["value"].strip():
                token = row["value"].strip()
    except Exception:
        pass
    return {"Authorization": f"Discogs token={token}", "User-Agent": "SleeveNotes/1.0"}

# ── DB ────────────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

SETTINGS_DEFAULTS: dict[str, str] = {
    "clean_artists":        "true",
    "include_pp":           "false",
    "hide_obvious_formats": "true",
    "hidden_format_tags":   "Album, LP, Stereo, Vinyl",
    "discogs_username":     "",
    "discogs_token":        "",
    "discogs_field_mappings": "{}",
}


def init_db():
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS records (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            discogs_id  TEXT NOT NULL,
            instance_id TEXT,
            folder_id   INTEGER,
            cat_no      TEXT,
            artist      TEXT,
            title       TEXT,
            label       TEXT,
            year        INTEGER,
            format      TEXT,
            cover_file  TEXT,
            is_new      TEXT,
            curr_cond   TEXT,
            sleeve_cond TEXT,
            retailer    TEXT,
            order_ref   TEXT,
            purchase_date TEXT,
            price       REAL,
            pp          REAL,
            notes       TEXT,
            valuation   REAL NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at  TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS images (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            discogs_id TEXT NOT NULL,
            filename   TEXT NOT NULL,
            seq        INTEGER NOT NULL,
            is_cover   INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS tracklist (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            discogs_id TEXT NOT NULL,
            position   TEXT,
            title      TEXT,
            duration   TEXT,
            type       TEXT NOT NULL DEFAULT 'track',
            seq        INTEGER NOT NULL
        );
        """)
        # Seed default settings (INSERT OR IGNORE preserves user changes)
        for key, value in SETTINGS_DEFAULTS.items():
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

init_db()

# ── Models ────────────────────────────────────────────────────────────────────

class RecordIn(BaseModel):
    discogs_id: str
    cat_no: Optional[str] = ""
    artist: Optional[str] = ""
    title: Optional[str] = ""
    label: Optional[str] = ""
    year: Optional[int] = None
    format: Optional[str] = ""
    cover_file: Optional[str] = ""
    is_new: Optional[str] = None
    curr_cond: Optional[str] = ""
    sleeve_cond: Optional[str] = ""
    retailer: Optional[str] = ""
    order_ref: Optional[str] = ""
    purchase_date: Optional[str] = ""
    price: Optional[float] = None
    pp: Optional[float] = None
    notes: Optional[str] = ""
    valuation: float = 0.0

class RecordUpdate(RecordIn):
    pass

# ── Helpers ───────────────────────────────────────────────────────────────────

def normalise_date(s: str) -> str:
    """Convert D/M/YYYY or DD/MM/YYYY to YYYY-MM-DD; pass through YYYY-MM-DD; else ''."""
    s = (s or "").strip()
    if not s:
        return ""
    # Already ISO
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        pass
    # DD/MM/YYYY or D/M/YYYY — strptime %d/%m accepts single-digit values
    try:
        return datetime.strptime(s, "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        pass
    return ""

def row_to_dict(row):
    d = dict(row)
    d["is_new"] = d["is_new"] or None
    return d

def find_cached_image(release_id: str) -> str:
    """Return a cached image filename for a release if one exists on disk.
    Checks new _01 suffix format first, falls back to legacy unsuffixed format."""
    rid = release_id.lstrip("r")
    for pattern in [f"r{rid}_01.*", f"r{rid}.*"]:
        matches = [m for m in IMAGES_DIR.glob(pattern) if m.is_file()]
        if matches:
            return matches[0].name
    return ""

async def download_all_images(images_data: list, release_id: str, headers: dict) -> list[dict]:
    """Download all images for a release (capped at 8). Returns list of {filename, seq}."""
    results = []
    async with httpx.AsyncClient(timeout=15) as client:
        for i, img in enumerate(images_data[:8], start=1):
            url = img.get("uri", "")
            if not url:
                continue
            ext = url.split(".")[-1].split("?")[0] or "jpg"
            filename = f"{release_id}_{i:02d}.{ext}"
            dest = IMAGES_DIR / filename
            if not dest.exists():
                try:
                    r = await client.get(url, headers=headers)
                    if r.status_code == 200:
                        dest.write_bytes(r.content)
                except Exception:
                    pass
            if dest.exists():
                results.append({"filename": filename, "seq": i})
    return results

def upsert_images(discogs_id: str, downloaded: list[dict], preserve_cover: bool = False) -> str:
    """Sync image rows for a release. Returns the filename to use as cover_file."""
    with get_db() as conn:
        current_cover = None
        if preserve_cover:
            row = conn.execute(
                "SELECT filename FROM images WHERE discogs_id = ? AND is_cover = 1",
                (discogs_id,)
            ).fetchone()
            current_cover = row["filename"] if row else None

        conn.execute("DELETE FROM images WHERE discogs_id = ?", (discogs_id,))
        for img in downloaded:
            is_cover = 1 if (current_cover and img["filename"] == current_cover) else 0
            conn.execute(
                "INSERT INTO images (discogs_id, filename, seq, is_cover) VALUES (?,?,?,?)",
                (discogs_id, img["filename"], img["seq"], is_cover)
            )

        cover_row = conn.execute(
            "SELECT filename FROM images WHERE discogs_id = ? AND is_cover = 1 LIMIT 1",
            (discogs_id,)
        ).fetchone()
        if not cover_row:
            cover_row = conn.execute(
                "SELECT filename FROM images WHERE discogs_id = ? ORDER BY seq LIMIT 1",
                (discogs_id,)
            ).fetchone()
        return cover_row["filename"] if cover_row else (downloaded[0]["filename"] if downloaded else "")

def upsert_tracklist(discogs_id: str, tracks: list):
    with get_db() as conn:
        conn.execute("DELETE FROM tracklist WHERE discogs_id = ?", (discogs_id,))
        for seq, t in enumerate(tracks):
            conn.execute(
                "INSERT INTO tracklist (discogs_id, position, title, duration, type, seq) VALUES (?,?,?,?,?,?)",
                (discogs_id, t.get("position", ""), t.get("title", ""),
                 t.get("duration", ""), t.get("type_", "track"), seq)
            )

# ── Collection import helpers ─────────────────────────────────────────────────

DISCOGS_SOURCED = {"artist", "title", "label", "cat_no", "year", "format"}

DISCOGS_CONDITION_MAP = {
    "Mint (M)":               "M",
    "Near Mint (NM or M-)":   "NM",
    "Very Good Plus (VG+)":   "VG+",
    "Very Good (VG)":         "VG",
    "Good Plus (G+)":         "G+",
    "Good (G)":               "G",
    "Fair (F)":               "F",
    "Poor (P)":               "P",
}

def normalise_condition(val: str) -> str:
    return DISCOGS_CONDITION_MAP.get(val.strip(), val.strip())
MAPPED_WRITEABLE = {"purchase_date", "price", "pp", "retailer", "order_ref",
                    "curr_cond", "sleeve_cond", "notes", "is_new"}

def parse_collection_item(item: dict, field_mappings: dict) -> dict:
    info = item.get("basic_information", {})
    rid = f"r{info['id']}"
    labels = info.get("labels", [])
    formats = info.get("formats", [])
    fmt_parts = [formats[0].get("name", "")] if formats else []
    if formats and formats[0].get("descriptions"):
        fmt_parts.extend(formats[0]["descriptions"])
    fmt = ", ".join(sorted(p for p in fmt_parts if p))
    record: dict = {
        "discogs_id": rid,
        "instance_id": str(item["instance_id"]),
        "folder_id": item.get("folder_id", 1),
        "artist": ", ".join(a["name"] for a in info.get("artists", [])),
        "title": info.get("title", ""),
        "label": labels[0].get("name", "") if labels else "",
        "cat_no": labels[0].get("catno", "") if labels else "",
        "year": info.get("year"),
        "format": fmt.strip(),
    }
    notes_map = {str(n["field_id"]): n["value"] for n in item.get("notes", [])}
    for field_id, db_col in field_mappings.items():
        if not db_col:
            continue
        raw = notes_map.get(field_id)
        if raw is None or str(raw).strip() == "":
            record[db_col] = None  # explicit None so "Discogs →" can clear SN values
            continue
        val: object = raw
        if db_col == "purchase_date":
            val = normalise_date(str(val))
        elif db_col in ("price", "pp", "valuation"):
            try:
                cleaned = re.sub(r"[^\d.]", "", str(val))
                val = float(cleaned) if cleaned else None
            except (ValueError, TypeError):
                val = None
        elif db_col in ("curr_cond", "sleeve_cond"):
            val = normalise_condition(str(val))
        record[db_col] = str(val).strip() or None
    return record


def compute_diff(parsed_items: list[dict]) -> dict:
    """Compare a list of pre-parsed flat record dicts against the SN database."""
    with get_db() as conn:
        fm_row = conn.execute("SELECT value FROM settings WHERE key='discogs_field_mappings'").fetchone()
        db_rows = conn.execute("SELECT * FROM records WHERE deleted_at IS NULL").fetchall()
    try:
        field_mappings = json.loads(fm_row["value"] if fm_row else "{}")
    except json.JSONDecodeError:
        field_mappings = {}
    db_records = [row_to_dict(r) for r in db_rows]
    db_by_instance = {r["instance_id"]: r for r in db_records if r.get("instance_id")}
    db_by_discogs  = {r["discogs_id"]: r for r in db_records if r.get("discogs_id")}
    matched_ids: set = set()
    mapped_cols = {v for v in field_mappings.values() if v}
    compare_cols = DISCOGS_SOURCED | mapped_cols
    result: dict = {"new": [], "changed": [], "unchanged": [], "db_only": []}
    for prospective in parsed_items:
        db_rec = db_by_instance.get(prospective.get("instance_id"))
        if not db_rec and prospective.get("discogs_id") and db_by_discogs.get(prospective["discogs_id"]):
            db_rec = db_by_discogs[prospective["discogs_id"]]
            log.info("Matched %s via discogs_id fallback (stored instance_id=%r, live=%r)",
                     prospective["discogs_id"], db_rec.get("instance_id"), prospective.get("instance_id"))
        if not db_rec:
            result["new"].append(prospective)
        else:
            matched_ids.add(db_rec["id"])
            changes = {}
            for col in compare_cols:
                new_val = prospective.get(col)
                old_val = db_rec.get(col)
                # For numeric fields with a 0 default, treat None (blank from source) and
                # 0/0.0 (DB default meaning "not entered") as equivalent — avoids false positives.
                if col in ("price", "pp", "valuation"):
                    if new_val is None and (old_val is None or old_val == 0):
                        continue
                new_str = "" if new_val is None else str(new_val).strip()
                old_str = "" if old_val is None else str(old_val).strip()
                if not new_str and not old_str:
                    continue
                if new_str != old_str:
                    changes[col] = {"from": old_val, "to": new_val}
            if changes:
                result["changed"].append({
                    "record_id": db_rec["id"],
                    "current": db_rec,
                    "prospective": prospective,
                    "changes": changes,
                })
            else:
                result["unchanged"].append({
                    "record_id": db_rec["id"],
                    "artist": db_rec.get("artist", ""),
                    "title": db_rec.get("title", ""),
                })
    for rec in db_records:
        if rec["id"] not in matched_ids:
            result["db_only"].append(rec)
    return result


def parse_discogs_csv_row(row: dict, name_to_db_col: dict) -> dict | None:
    """Parse one row of a Discogs-format CSV (or SN export) into a flat record dict."""
    release_id = (row.get("release_id") or "").strip()
    if not release_id:
        return None
    record: dict = {
        "discogs_id": f"r{release_id}",
        "instance_id": (row.get("SN_instance_id") or row.get("instance_id") or "").strip() or None,
        "artist": (row.get("Artist") or "").strip(),
        "title": (row.get("Title") or "").strip(),
        "label": (row.get("Label") or "").strip(),
        "cat_no": (row.get("Catalog#") or "").strip(),
        "format": (row.get("Format") or "").strip(),
    }
    try:
        record["year"] = int(row.get("Released") or 0) or None
    except (ValueError, TypeError):
        record["year"] = None
    try:
        record["folder_id"] = int(row.get("CollectionFolder") or row.get("folder_id") or 1)
    except (ValueError, TypeError):
        record["folder_id"] = 1

    # Standard condition columns
    for csv_col, db_col in (("Collection Media Condition", "curr_cond"),
                             ("Collection Sleeve Condition", "sleeve_cond")):
        val = (row.get(csv_col) or "").strip()
        record[db_col] = normalise_condition(val) if val else None

    # Raw DB column names (SN export fallback; try SN_ prefix first, then bare name)
    for db_col in ("retailer", "order_ref", "purchase_date", "price", "pp", "notes", "valuation",
                   "is_new", "cover_file", "curr_cond", "sleeve_cond"):
        if db_col in record:
            continue
        val = (row.get(f"SN_{db_col}") or row.get(db_col) or "").strip()
        if not val:
            continue
        if db_col == "purchase_date":
            record[db_col] = normalise_date(val)
        elif db_col in ("price", "pp", "valuation"):
            try:
                cleaned = re.sub(r"[^\d.]", "", val)
                record[db_col] = float(cleaned) if cleaned else None
            except (ValueError, TypeError):
                record[db_col] = None
        elif db_col in ("curr_cond", "sleeve_cond"):
            record[db_col] = normalise_condition(val) or None
        elif db_col == "is_new":
            record[db_col] = val or None
        else:
            record[db_col] = val

    # Custom Collection [Field Name] columns (highest priority — override raw DB cols)
    for field_name, db_col in name_to_db_col.items():
        if not db_col:
            continue
        val = (row.get(f"Collection {field_name}") or "").strip()
        if not val:
            continue
        if db_col == "purchase_date":
            record[db_col] = normalise_date(val)
        elif db_col in ("price", "pp", "valuation"):
            try:
                cleaned = re.sub(r"[^\d.]", "", val)
                record[db_col] = float(cleaned) if cleaned else None
            except (ValueError, TypeError):
                record[db_col] = None
        elif db_col in ("curr_cond", "sleeve_cond"):
            record[db_col] = normalise_condition(val) or None
        else:
            record[db_col] = val

    return record


# ── Routes: Discogs collection import ────────────────────────────────────────

@app.get("/api/collection/fields")
async def collection_fields():
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='discogs_username'").fetchone()
    username = (row["value"] if row else "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Discogs username not configured")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await discogs_get(
            client,
            f"https://api.discogs.com/users/{username}/collection/fields",
            headers=get_discogs_headers(),
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Discogs API error")
    return resp.json()


@app.get("/api/collection/preview")
async def collection_preview(record_id: int = None):
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings = {r["key"]: r["value"] for r in rows}
    username = settings.get("discogs_username", "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Discogs username not configured")
    try:
        field_mappings: dict = json.loads(settings.get("discogs_field_mappings", "{}"))
    except json.JSONDecodeError:
        field_mappings = {}

    hdrs = get_discogs_headers()
    async with httpx.AsyncClient(timeout=20) as client:
        first = await discogs_get(
            client,
            f"https://api.discogs.com/users/{username}/collection/folders/0/releases",
            params={"per_page": 100, "page": 1},
            headers=hdrs,
        )
        if first.status_code != 200:
            raise HTTPException(status_code=first.status_code, detail="Discogs API error")
        data = first.json()
        pages = data["pagination"]["pages"]
        items = data["releases"]
        if pages > 1:
            responses = await asyncio.gather(*[
                discogs_get(
                    client,
                    f"https://api.discogs.com/users/{username}/collection/folders/0/releases",
                    params={"per_page": 100, "page": p},
                    headers=hdrs,
                )
                for p in range(2, min(pages + 1, 11))
            ])
            for resp in responses:
                if resp.status_code == 200:
                    items.extend(resp.json()["releases"])

    items.sort(key=lambda x: x.get("instance_id", 0))
    parsed = [parse_collection_item(item, field_mappings) for item in items]
    diff = compute_diff(parsed)
    if record_id is not None:
        diff["new"] = []
        diff["changed"]   = [r for r in diff["changed"]   if r["record_id"] == record_id]
        diff["unchanged"] = [r for r in diff["unchanged"] if r["record_id"] == record_id]
        diff["db_only"]   = [r for r in diff["db_only"]   if r["id"]        == record_id]
    return diff


# ── Routes: Discogs sync ──────────────────────────────────────────────────────

class SyncFieldUpdate(BaseModel):
    field_id: str
    value: str

class SyncToSleeveNotes(BaseModel):
    action: str  # "create" or "update"
    record_id: Optional[int] = None
    prospective: dict

class SyncToDiscogs(BaseModel):
    action: str  # "create" or "update"
    record_id: Optional[int] = None
    instance_id: Optional[str] = None
    discogs_id: str
    folder_id: int = 1
    updates: list[SyncFieldUpdate]

class SyncPayload(BaseModel):
    to_sleevenotes: list[SyncToSleeveNotes]
    to_discogs: list[SyncToDiscogs]

def _insert_record(conn, rec: dict) -> int:
    is_new = str(rec["is_new"]).strip() if rec.get("is_new") not in (None, "") else None
    cur = conn.execute("""
        INSERT INTO records
          (discogs_id, instance_id, folder_id, cat_no, artist, title, label, year, format,
           cover_file, is_new, curr_cond, sleeve_cond, retailer, order_ref,
           purchase_date, price, pp, notes, valuation)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        rec.get("discogs_id", ""), rec.get("instance_id", ""),
        int(rec.get("folder_id") or 1),
        rec.get("cat_no", ""), rec.get("artist", ""), rec.get("title", ""),
        rec.get("label", ""), rec.get("year"), rec.get("format", ""),
        rec.get("cover_file") or find_cached_image(rec.get("discogs_id", "")),
        is_new, rec.get("curr_cond") or None, rec.get("sleeve_cond") or None,
        rec.get("retailer", ""),
        rec.get("order_ref", ""),
        normalise_date(str(rec.get("purchase_date", "") or "")),
        (float(rec["price"]) if rec.get("price") not in (None, "") else None),
        (float(rec["pp"]) if rec.get("pp") not in (None, "") else None),
        rec.get("notes", ""), 0.0,
    ))
    return cur.lastrowid

async def _refresh_from_discogs(client, hdrs: dict, record_id: int, discogs_id: str):
    """Fetch images and valuation from Discogs for a record. Silently ignores failures."""
    try:
        rid = discogs_id.lstrip("r")
        release_resp, stats_resp = await asyncio.gather(
            discogs_get(client, f"https://api.discogs.com/releases/{rid}", headers=hdrs),
            discogs_get(client, f"https://api.discogs.com/marketplace/stats/{rid}", headers=hdrs),
        )
        if release_resp.status_code != 200:
            return
        data = release_resp.json()
        downloaded = await download_all_images(data.get("images", []), f"r{rid}", hdrs)
        cover_file = upsert_images(f"r{rid}", downloaded, preserve_cover=False)
        upsert_tracklist(f"r{rid}", data.get("tracklist", []))
        stats = stats_resp.json() if stats_resp.status_code == 200 else {}
        lp = stats.get("lowest_price") or {}
        valuation = float(lp.get("value") or 0)
        with get_db() as conn:
            conn.execute(
                "UPDATE records SET cover_file=?, valuation=? WHERE id=?",
                (cover_file or "", valuation, record_id),
            )
    except Exception:
        pass

async def _push_field_updates(client, username: str, hdrs: dict,
                               rid: str, instance_id: str, folder_id: int,
                               updates: list[SyncFieldUpdate]) -> list[dict]:
    errors = []
    for upd in updates:
        url = (f"https://api.discogs.com/users/{username}/collection"
               f"/folders/{folder_id}/releases/{rid}"
               f"/instances/{instance_id}/fields/{upd.field_id}")
        try:
            log.info("Discogs POST %s  value=%r", url, upd.value)
            resp = await discogs_post(client, url, json={"value": upd.value}, headers=hdrs)
            log.info("Discogs response %s  body=%s", resp.status_code, resp.text[:300])
            if resp.status_code == 422:
                log.warning("Field %s rejected (dropdown value not in options?): %s", upd.field_id, resp.text[:200])
            elif resp.status_code not in (200, 201, 204):
                errors.append({"error": f"HTTP {resp.status_code}: {resp.text[:200]}"})
        except Exception as e:
            log.exception("Discogs field update failed")
            errors.append({"error": str(e)})
    return errors

async def _refresh_new_records(new_records: list[tuple[int, str]], hdrs: dict):
    async with httpx.AsyncClient(timeout=30) as client:
        await asyncio.gather(*[
            _refresh_from_discogs(client, hdrs, rec_id, did)
            for rec_id, did in new_records
        ])

@app.post("/api/collection/sync")
async def collection_sync(payload: SyncPayload, background_tasks: BackgroundTasks):
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='discogs_username'").fetchone()
    username = (row["value"] if row else "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Discogs username not configured")

    hdrs = get_discogs_headers()
    stats = {"sn_created": 0, "sn_updated": 0,
             "discogs_created": 0, "discogs_updated": 0,
             "failed": 0, "errors": []}

    # SleeveNotes DB writes
    new_records: list[tuple[int, str]] = []  # (record_id, discogs_id) for post-insert refresh
    with get_db() as conn:
        for item in payload.to_sleevenotes:
            try:
                if item.action == "create":
                    row_id = _insert_record(conn, item.prospective)
                    new_records.append((row_id, item.prospective.get("discogs_id", "")))
                    stats["sn_created"] += 1
                else:
                    p = item.prospective
                    update_fields = {k: v for k, v in p.items()
                                     if k in DISCOGS_SOURCED | MAPPED_WRITEABLE | {"instance_id", "folder_id"}}
                    if update_fields:
                        clause = ", ".join(f"{k}=?" for k in update_fields)
                        conn.execute(f"UPDATE records SET {clause} WHERE id=?",
                                     [*update_fields.values(), item.record_id])
                    stats["sn_updated"] += 1
            except Exception as e:
                stats["failed"] += 1
                stats["errors"].append({"side": "sleevenotes", "error": str(e)})

    if new_records:
        background_tasks.add_task(_refresh_new_records, new_records, hdrs)
        stats["sn_refreshing"] = len(new_records)

    # Discogs updates — rate limited
    async with httpx.AsyncClient(timeout=10) as client:
        for i, item in enumerate(payload.to_discogs):
            rid = item.discogs_id.lstrip("r")
            instance_id = item.instance_id
            folder_id = item.folder_id

            if item.action == "create":
                try:
                    add_resp = await discogs_post(
                        client,
                        f"https://api.discogs.com/users/{username}/collection/folders/1/releases/{rid}",
                        headers=hdrs,
                    )
                    if add_resp.status_code != 201:
                        stats["failed"] += 1
                        stats["errors"].append({"discogs_id": item.discogs_id,
                                                "error": f"Add failed HTTP {add_resp.status_code}: {add_resp.text[:200]}"})
                        continue
                    add_data = add_resp.json()
                    instance_id = str(add_data["instance_id"])
                    folder_id = add_data.get("folder_id", 1)
                    if item.record_id:
                        with get_db() as conn:
                            conn.execute("UPDATE records SET instance_id=?, folder_id=? WHERE id=?",
                                         (instance_id, folder_id, item.record_id))
                    stats["discogs_created"] += 1
                except Exception as e:
                    stats["failed"] += 1
                    stats["errors"].append({"discogs_id": item.discogs_id, "error": str(e)})
                    continue
            else:
                stats["discogs_updated"] += 1
                # Back-fill instance_id / folder_id if the record didn't have them
                if instance_id and item.record_id:
                    with get_db() as conn:
                        conn.execute(
                            "UPDATE records SET instance_id=?, folder_id=? WHERE id=? AND (instance_id IS NULL OR instance_id='')",
                            (instance_id, folder_id, item.record_id),
                        )

            if item.updates and instance_id:
                errs = await _push_field_updates(client, username, hdrs, rid, instance_id, folder_id, item.updates)
                if errs:
                    stats["failed"] += len(errs)
                    stats["errors"].extend(errs)
            elif item.updates:
                log.warning("Skipping field updates for %s — instance_id is missing", item.discogs_id)

    return stats


# ── Routes: Discogs ───────────────────────────────────────────────────────────

@app.get("/api/discogs/{release_id}")
async def fetch_discogs(release_id: str):
    rid = release_id.lstrip("r")
    hdrs = get_discogs_headers()
    async with httpx.AsyncClient(timeout=10) as client:
        release_resp, stats_resp = await asyncio.gather(
            discogs_get(client, f"https://api.discogs.com/releases/{rid}", headers=hdrs),
            discogs_get(client, f"https://api.discogs.com/marketplace/stats/{rid}", headers=hdrs),
        )
    if release_resp.status_code != 200:
        raise HTTPException(status_code=release_resp.status_code, detail="Discogs fetch failed")
    data = release_resp.json()
    downloaded = await download_all_images(data.get("images", []), f"r{rid}", hdrs)
    cover_file = upsert_images(f"r{rid}", downloaded, preserve_cover=False)
    upsert_tracklist(f"r{rid}", data.get("tracklist", []))
    labels = data.get("labels", [])
    label = labels[0].get("name", "") if labels else ""
    cat_no = labels[0].get("catno", "") if labels else ""
    formats = data.get("formats", [])
    fmt_parts = [formats[0].get("name", "")] if formats else []
    if formats and formats[0].get("descriptions"):
        fmt_parts.extend(formats[0]["descriptions"])
    fmt = ", ".join(sorted(p for p in fmt_parts if p))
    stats = stats_resp.json() if stats_resp.status_code == 200 else {}
    lp = stats.get("lowest_price") or {}
    valuation = float(lp.get("value") or 0)
    return {
        "discogs_id": f"r{rid}",
        "artist": ", ".join(a["name"] for a in data.get("artists", [])),
        "title": data.get("title", ""),
        "label": label,
        "cat_no": cat_no,
        "year": data.get("year"),
        "format": fmt.strip(),
        "cover_file": cover_file,
        "valuation": valuation,
    }

# ── Routes: Records ───────────────────────────────────────────────────────────

@app.get("/api/records")
def list_records():
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM records WHERE deleted_at IS NULL ORDER BY CAST(instance_id AS INTEGER), id"
            ).fetchall()
        return [row_to_dict(r) for r in rows]
    except sqlite3.OperationalError:
        init_db()
        return []

@app.post("/api/records", status_code=201)
def create_record(rec: RecordIn):
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO records
              (discogs_id,cat_no,artist,title,label,year,format,cover_file,
               is_new,curr_cond,sleeve_cond,retailer,order_ref,purchase_date,price,pp,notes,valuation)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            rec.discogs_id, rec.cat_no, rec.artist, rec.title, rec.label,
            rec.year, rec.format, rec.cover_file, rec.is_new or None,
            rec.curr_cond or None, rec.sleeve_cond or None, rec.retailer,
            rec.order_ref, rec.purchase_date, rec.price, rec.pp, rec.notes, rec.valuation,
        ))
        return {"id": cur.lastrowid}

@app.put("/api/records/{record_id}")
def update_record(record_id: int, rec: RecordUpdate):
    with get_db() as conn:
        conn.execute("""
            UPDATE records SET
              discogs_id=?,cat_no=?,artist=?,title=?,label=?,year=?,format=?,cover_file=?,
              is_new=?,curr_cond=?,sleeve_cond=?,retailer=?,order_ref=?,purchase_date=?,price=?,pp=?,notes=?,valuation=?
            WHERE id=?
        """, (
            rec.discogs_id, rec.cat_no, rec.artist, rec.title, rec.label,
            rec.year, rec.format, rec.cover_file,
            rec.is_new or None,
            rec.curr_cond or None, rec.sleeve_cond or None, rec.retailer,
            rec.order_ref, rec.purchase_date, rec.price, rec.pp, rec.notes, rec.valuation,
            record_id,
        ))
    return {"ok": True}

@app.delete("/api/records/{record_id}")
def delete_record(record_id: int):
    with get_db() as conn:
        conn.execute(
            "UPDATE records SET deleted_at = datetime('now') WHERE id = ?", (record_id,)
        )
    return {"ok": True}

# ── Routes: Discogs refresh ───────────────────────────────────────────────────

@app.post("/api/records/{record_id}/refresh")
async def refresh_record(record_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Record not found")

    rid = str(row["discogs_id"]).lstrip("r")
    hdrs = get_discogs_headers()
    async with httpx.AsyncClient(timeout=10) as client:
        release_resp, stats_resp = await asyncio.gather(
            discogs_get(client, f"https://api.discogs.com/releases/{rid}", headers=hdrs),
            discogs_get(client, f"https://api.discogs.com/marketplace/stats/{rid}", headers=hdrs),
        )

    if release_resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Discogs unavailable")

    data = release_resp.json()
    downloaded = await download_all_images(data.get("images", []), f"r{rid}", hdrs)
    cover_file = upsert_images(f"r{rid}", downloaded, preserve_cover=True) or row["cover_file"]
    upsert_tracklist(f"r{rid}", data.get("tracklist", []))
    labels = data.get("labels", [])
    label = labels[0].get("name", "") if labels else ""
    cat_no = labels[0].get("catno", "") if labels else ""
    formats = data.get("formats", [])
    fmt_parts = [formats[0].get("name", "")] if formats else []
    if formats and formats[0].get("descriptions"):
        fmt_parts.extend(formats[0]["descriptions"])
    fmt = ", ".join(sorted(p for p in fmt_parts if p))

    stats = stats_resp.json() if stats_resp.status_code == 200 else {}
    lp = stats.get("lowest_price") or {}
    valuation = float(lp.get("value") or 0)

    with get_db() as conn:
        conn.execute("""
            UPDATE records
               SET artist=?, title=?, label=?, cat_no=?, year=?, format=?, cover_file=?, valuation=?
             WHERE id=?
        """, (
            ", ".join(a["name"] for a in data.get("artists", [])),
            data.get("title", ""), label, cat_no, data.get("year"),
            fmt.strip(), cover_file, valuation, record_id,
        ))
    return {"ok": True}

# ── Routes: Settings ─────────────────────────────────────────────────────────

class SettingIn(BaseModel):
    value: str

@app.get("/api/settings")
def get_settings():
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}

@app.put("/api/settings/{key}")
def update_setting(key: str, body: SettingIn):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, body.value),
        )
    return {"ok": True}

# ── Routes: Admin ────────────────────────────────────────────────────────────

@app.post("/api/admin/format")
def format_db():
    """Delete all records, leaving settings intact."""
    with get_db() as conn:
        conn.execute("DELETE FROM records")
        conn.execute("DELETE FROM tracklist")
        conn.execute("DELETE FROM sqlite_sequence WHERE name='records'")
    return {"ok": True}


@app.post("/api/admin/factory-reset")
def factory_reset():
    """Delete all records and restore all settings to their defaults."""
    with get_db() as conn:
        conn.execute("DELETE FROM records")
        conn.execute("DELETE FROM tracklist")
        conn.execute("DELETE FROM sqlite_sequence WHERE name='records'")
        for key, value in SETTINGS_DEFAULTS.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
    return {"ok": True}

@app.post("/api/admin/clear-images")
def clear_images():
    deleted = 0
    for f in IMAGES_DIR.iterdir():
        if f.is_file():
            f.unlink()
            deleted += 1
    with get_db() as conn:
        conn.execute("UPDATE records SET cover_file = ''")
        conn.execute("DELETE FROM images")
    return {"deleted": deleted}

# ── Routes: Record sub-resources ─────────────────────────────────────────────

@app.get("/api/records/{record_id}/tracklist")
def get_record_tracklist(record_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT discogs_id FROM records WHERE id = ?", (record_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404)
        tracks = conn.execute(
            "SELECT position, title, duration, type FROM tracklist WHERE discogs_id = ? ORDER BY seq",
            (row["discogs_id"],)
        ).fetchall()
    return [dict(t) for t in tracks]

@app.get("/api/records/{record_id}/images")
def get_record_images(record_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT discogs_id FROM records WHERE id = ?", (record_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404)
        images = conn.execute(
            "SELECT filename, seq, is_cover FROM images WHERE discogs_id = ? ORDER BY seq",
            (row["discogs_id"],)
        ).fetchall()
    return [dict(i) for i in images]

class SetCoverIn(BaseModel):
    filename: str

@app.post("/api/records/{record_id}/set-cover")
def set_cover(record_id: int, body: SetCoverIn):
    with get_db() as conn:
        row = conn.execute("SELECT discogs_id FROM records WHERE id = ?", (record_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404)
        did = row["discogs_id"]
        conn.execute("UPDATE images SET is_cover = 0 WHERE discogs_id = ?", (did,))
        conn.execute(
            "UPDATE images SET is_cover = 1 WHERE discogs_id = ? AND filename = ?",
            (did, body.filename)
        )
        conn.execute("UPDATE records SET cover_file = ? WHERE id = ?", (body.filename, record_id))
    return {"ok": True}

# ── Routes: Import / Export ───────────────────────────────────────────────────

async def _fetch_discogs_field_names(username: str) -> dict[str, str]:
    """Return {field_id: field_name} from the Discogs fields API, or {} on failure."""
    if not username:
        return {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await discogs_get(
                client,
                f"https://api.discogs.com/users/{username}/collection/fields",
                headers=get_discogs_headers(),
            )
        if resp.status_code == 200:
            return {str(f["id"]): f["name"] for f in resp.json().get("fields", [])}
    except Exception:
        pass
    return {}


@app.post("/api/import/csv")
async def import_csv_discogs(file: UploadFile = File(...)):
    """Parse a Discogs-format CSV and return a diff preview (same shape as /api/collection/preview)."""
    content = (await file.read()).decode("utf-8-sig")  # strip BOM if present
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings = {r["key"]: r["value"] for r in rows}
    username = settings.get("discogs_username", "").strip()
    try:
        field_mappings: dict = json.loads(settings.get("discogs_field_mappings", "{}"))
    except json.JSONDecodeError:
        field_mappings = {}

    id_to_name = await _fetch_discogs_field_names(username)
    name_to_db_col: dict[str, str] = {}
    for field_id, db_col in field_mappings.items():
        if db_col and field_id in id_to_name:
            name_to_db_col[id_to_name[field_id]] = db_col

    reader = csv.DictReader(io.StringIO(content))
    parsed_items: list[dict] = []
    for row in reader:
        item = parse_discogs_csv_row(row, name_to_db_col)
        if item:
            parsed_items.append(item)

    parsed_items.sort(key=lambda x: int(x.get("instance_id") or 0))
    diff = compute_diff(parsed_items)
    diff["db_only"] = []  # CSV import is partial — records absent from the CSV are left untouched
    return diff


# Standard Discogs CSV column name mappings for export
_EXPORT_STANDARD = [
    ("discogs_id",  "release_id"),
    ("folder_id",   "CollectionFolder"),
    ("cat_no",      "Catalog#"),
    ("artist",      "Artist"),
    ("title",       "Title"),
    ("label",       "Label"),
    ("format",      "Format"),
    ("year",        "Released"),
    ("created_at",  "Date Added"),
    ("curr_cond",   "Collection Media Condition"),
    ("sleeve_cond", "Collection Sleeve Condition"),
]
_EXPORT_MAPPABLE = ("retailer", "order_ref", "purchase_date", "is_new", "price", "pp", "notes", "valuation")
# SN-specific columns appended after all Discogs columns
_EXPORT_SN_EXTRAS = ("id", "instance_id", "is_new", "cover_file")


@app.get("/api/export")
async def export_csv():
    with get_db() as conn:
        db_rows = conn.execute(
            "SELECT * FROM records WHERE deleted_at IS NULL ORDER BY CAST(instance_id AS INTEGER), id"
        ).fetchall()
        settings_rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings = {r["key"]: r["value"] for r in settings_rows}
    try:
        field_mappings: dict = json.loads(settings.get("discogs_field_mappings", "{}"))
    except json.JSONDecodeError:
        field_mappings = {}

    username = settings.get("discogs_username", "").strip()
    id_to_name = await _fetch_discogs_field_names(username)
    # db_col → "Collection [Field Name]" for mapped fields
    mapped_headers: dict[str, str] = {}
    for field_id, db_col in field_mappings.items():
        if db_col:
            name = id_to_name.get(field_id, field_id)
            mapped_headers[db_col] = f"Collection {name}"

    # Build ordered column list: standard Discogs cols → mapped custom → unmapped SN → SN extras
    headers: list[str] = [csv_col for _, csv_col in _EXPORT_STANDARD]
    for db_col in _EXPORT_MAPPABLE:
        if db_col in mapped_headers:
            headers.append(mapped_headers[db_col])
        else:
            headers.append(f"SN_{db_col}")
    headers.extend(f"SN_{col}" for col in _EXPORT_SN_EXTRAS)

    def get_val(d: dict, csv_col: str) -> str:
        # Reverse-map csv_col → db_col
        for db_col, col in _EXPORT_STANDARD:
            if col == csv_col:
                val = d.get(db_col)
                if db_col == "discogs_id":
                    return str(val or "").lstrip("r")
                return str(val) if val is not None else ""
        # Mapped custom col
        for db_col, col in mapped_headers.items():
            if col == csv_col:
                val = d.get(db_col)
                return str(val) if val is not None else ""
        # Raw DB col (unmapped SN field) — strip SN_ prefix to get the actual db key
        db_col = csv_col[3:] if csv_col.startswith("SN_") else csv_col
        val = d.get(db_col)
        return str(val) if val is not None else ""

    records = [row_to_dict(r) for r in db_rows]

    def generate():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(headers)
        yield buf.getvalue()
        for d in records:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow([get_val(d, h) for h in headers])
            yield buf.getvalue()

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sleevenotes_export.csv"},
    )

# ── Static ────────────────────────────────────────────────────────────────────

app.mount("/images", StaticFiles(directory=str(IMAGES_DIR)), name="images")

STATIC_DIR = Path("static")

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    file = STATIC_DIR / full_path
    if file.is_file():
        return FileResponse(file)
    return FileResponse(STATIC_DIR / "index.html")
