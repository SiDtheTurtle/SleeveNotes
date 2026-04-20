import os
import io
import csv
import sqlite3
import asyncio
import httpx
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

DATA_DIR = Path("/data")
DB_PATH = DATA_DIR / "sleevenotes.db"
IMAGES_DIR = DATA_DIR / "images"
DISCOGS_TOKEN = os.environ.get("DISCOGS_TOKEN", "")
DISCOGS_HEADERS = {
    "Authorization": f"Discogs token={DISCOGS_TOKEN}",
    "User-Agent": "SleeveNotes/1.0",
}

app = FastAPI(title="SleeveNotes")

# ── DB ────────────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS records (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            discogs_id  TEXT NOT NULL,
            cat_no      TEXT,
            artist      TEXT,
            title       TEXT,
            label       TEXT,
            year        INTEGER,
            format      TEXT,
            cover_file  TEXT,
            is_new      INTEGER NOT NULL DEFAULT 0,
            orig_cond   TEXT,
            curr_cond   TEXT,
            status      TEXT NOT NULL DEFAULT 'In Collection',
            retailer    TEXT,
            order_ref   TEXT,
            purchase_date TEXT,
            price       REAL NOT NULL DEFAULT 0,
            pp          REAL NOT NULL DEFAULT 0,
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
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('clean_artists', 'true')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('include_pp', 'false')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('hide_obvious_formats', 'true')")
        # Migrations
        try:
            conn.execute("ALTER TABLE records ADD COLUMN deleted_at TEXT")
        except sqlite3.OperationalError:
            pass

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
    is_new: bool = False
    orig_cond: Optional[str] = ""
    curr_cond: Optional[str] = ""
    status: str = "In Collection"
    retailer: Optional[str] = ""
    order_ref: Optional[str] = ""
    purchase_date: Optional[str] = ""
    price: float = 0.0
    pp: float = 0.0
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
    d["is_new"] = bool(d["is_new"])
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

async def download_all_images(images_data: list, release_id: str) -> list[dict]:
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
                    r = await client.get(url, headers=DISCOGS_HEADERS)
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

# ── Routes: Discogs ───────────────────────────────────────────────────────────

@app.get("/api/discogs/{release_id}")
async def fetch_discogs(release_id: str):
    rid = release_id.lstrip("r")
    async with httpx.AsyncClient(timeout=10) as client:
        release_resp, stats_resp = await asyncio.gather(
            client.get(f"https://api.discogs.com/releases/{rid}", headers=DISCOGS_HEADERS),
            client.get(f"https://api.discogs.com/marketplace/stats/{rid}", headers=DISCOGS_HEADERS),
        )
    if release_resp.status_code != 200:
        raise HTTPException(status_code=release_resp.status_code, detail="Discogs fetch failed")
    data = release_resp.json()
    downloaded = await download_all_images(data.get("images", []), f"r{rid}")
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
def list_records(show_returned: bool = False):
    try:
        with get_db() as conn:
            if show_returned:
                rows = conn.execute(
                    "SELECT * FROM records WHERE deleted_at IS NULL ORDER BY id"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM records WHERE deleted_at IS NULL AND status != 'Returned' ORDER BY id"
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
               is_new,orig_cond,curr_cond,status,retailer,order_ref,purchase_date,price,pp,notes,valuation)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            rec.discogs_id, rec.cat_no, rec.artist, rec.title, rec.label,
            rec.year, rec.format, rec.cover_file, int(rec.is_new),
            rec.orig_cond, rec.curr_cond, rec.status, rec.retailer,
            rec.order_ref, rec.purchase_date, rec.price, rec.pp, rec.notes, rec.valuation,
        ))
        return {"id": cur.lastrowid}

@app.put("/api/records/{record_id}")
def update_record(record_id: int, rec: RecordUpdate):
    with get_db() as conn:
        conn.execute("""
            UPDATE records SET
              discogs_id=?,cat_no=?,artist=?,title=?,label=?,year=?,format=?,cover_file=?,
              orig_cond=?,curr_cond=?,status=?,retailer=?,order_ref=?,purchase_date=?,price=?,pp=?,notes=?,valuation=?
            WHERE id=?
        """, (
            rec.discogs_id, rec.cat_no, rec.artist, rec.title, rec.label,
            rec.year, rec.format, rec.cover_file,
            rec.orig_cond, rec.curr_cond, rec.status, rec.retailer,
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
    async with httpx.AsyncClient(timeout=10) as client:
        release_resp, stats_resp = await asyncio.gather(
            client.get(f"https://api.discogs.com/releases/{rid}", headers=DISCOGS_HEADERS),
            client.get(f"https://api.discogs.com/marketplace/stats/{rid}", headers=DISCOGS_HEADERS),
        )

    if release_resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Discogs unavailable")

    data = release_resp.json()
    downloaded = await download_all_images(data.get("images", []), f"r{rid}")
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
    with get_db() as conn:
        conn.execute("DELETE FROM records")
        conn.execute("DELETE FROM tracklist")
        conn.execute("DELETE FROM sqlite_sequence WHERE name='records'")
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

FIELDS = ["id","discogs_id","cat_no","artist","title","label","year","format",
          "cover_file","is_new","orig_cond","curr_cond","status","retailer","order_ref",
          "purchase_date","price","pp","notes","valuation"]

CSV_MAP = {
    # csv column → model field
    "discogsId": "discogs_id", "catNo": "cat_no", "origCond": "orig_cond",
    "currCond": "curr_cond", "orderRef": "order_ref", "date": "purchase_date",
}

@app.post("/api/import")
async def import_csv(file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8")
    reader = csv.DictReader(io.StringIO(content), delimiter="|")
    inserted = 0
    skipped = 0
    seen_ids = set()
    with get_db() as conn:
        for row in reader:
            # normalise keys
            norm = {}
            for k, v in row.items():
                mapped = CSV_MAP.get(k, k)
                norm[mapped] = v.strip() if v else ""
            # skip if discogs_id missing
            did = norm.get("discogs_id", "")
            if not did:
                continue
            # dedup by source id if present, otherwise by discogs_id
            row_id = norm.get("id", "").strip()
            dedup_key = f"id:{row_id}" if row_id else f"discogs:{did}"
            if dedup_key in seen_ids:
                skipped += 1
                continue
            seen_ids.add(dedup_key)
            if row_id:
                if conn.execute("SELECT 1 FROM records WHERE id = ?", (row_id,)).fetchone():
                    skipped += 1
                    continue
            elif conn.execute("SELECT 1 FROM records WHERE discogs_id = ?", (did,)).fetchone():
                skipped += 1
                continue
            # is_new: treat S (sealed) as new if column absent
            is_new = norm.get("is_new", "")
            if is_new == "":
                is_new = 1 if norm.get("orig_cond", "").upper() == "S" else 0
            else:
                is_new = 1 if str(is_new).lower() in ("1", "true", "yes") else 0
            try:
                price = float(norm.get("price", 0) or 0)
                pp = float(norm.get("pp", 0) or 0)
                year = int(norm.get("year", 0) or 0) or None
                valuation = float(norm.get("valuation", 0) or 0)
            except ValueError:
                price, pp, year, valuation = 0.0, 0.0, None, 0.0

            conn.execute("""
                INSERT INTO records
                  (discogs_id,cat_no,artist,title,label,year,format,cover_file,
                   is_new,orig_cond,curr_cond,status,retailer,order_ref,purchase_date,price,pp,notes,valuation)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                did, norm.get("cat_no",""), norm.get("artist",""),
                norm.get("title",""), norm.get("label",""), year,
                "", norm.get("cover_file","") or find_cached_image(did),
                is_new, norm.get("orig_cond",""), norm.get("curr_cond",""),
                norm.get("status","In Collection"), norm.get("retailer",""),
                norm.get("order_ref",""), normalise_date(norm.get("purchase_date", "")),
                price, pp, norm.get("notes",""), valuation,
            ))
            inserted += 1
    return {"inserted": inserted, "skipped": skipped}

@app.get("/api/export")
def export_csv():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM records WHERE deleted_at IS NULL ORDER BY id").fetchall()

    def generate():
        yield "|".join(FIELDS) + "\n"
        for row in rows:
            d = row_to_dict(row)
            yield "|".join(str(d.get(f, "")) for f in FIELDS) + "\n"

    return StreamingResponse(
        generate(),
        media_type="text/plain",
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
