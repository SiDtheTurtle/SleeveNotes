# SleeveNotes

A personal vinyl record collection manager. Built for my own use out of curiosity — not production software, not battle-tested, not ready for anyone else's data. Use at your own risk.

> **⚠️ Vibe-coded.** This project was built almost entirely through conversational prompting with [Claude Code](https://claude.ai/code). I directed, it typed. If the code looks a bit unusual in places, that's why. Issues and PRs are welcome but responses may be slow — this is a hobby project.

---

## What it does

- Tracks your vinyl record collection
- Looks up metadata, cover art, and tracklists from the [Discogs](https://www.discogs.com) API
- Pulls current valuations (lowest marketplace listing) from Discogs
- Table and tile views, with filtering by format tags and status
- Detail cards with image carousels and tracklists
- Bulk refresh of Discogs data
- Import/export via pipe-delimited CSV

## Stack

- **Backend:** Python 3.12, FastAPI, SQLite
- **Frontend:** Vanilla JS SPA — no framework, no build step
- **Container:** Docker Compose, port 2026

## Running it

You'll need a [Discogs API token](https://www.discogs.com/settings/developers).

1. Copy `sleevenotes.env.example` to `sleevenotes.env` and add your token:
   ```
   DISCOGS_TOKEN=your_token_here
   ```

2. Run:
   ```bash
   docker compose up -d
   ```

3. Open [http://localhost:2026](http://localhost:2026)

Data is persisted in a Docker volume (`sleevenotes_data`).

## Resetting the database

```bash
docker exec sleevenotes rm /data/sleevenotes.db
docker compose restart
```

---

*Personal project. Not affiliated with Discogs.*
