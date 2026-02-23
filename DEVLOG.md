# CV1 — Dev Log

This file tracks every meaningful change made to the project. Updated after each session.

---

## 2026-02-23 — Initial build + deploy prep

### What was built from scratch

**Apartment Rental Scout** — a self-hosted web app that automatically scrapes Romanian real-estate sites and shows you matching apartments in one dashboard.

---

### Feature: Search configuration (`config.py`)
- Target city: Bucharest
- Target neighborhoods: Floreasca, Dorobanți, Aviatorilor, Herăstrău, Băneasa, Domenii, Victoriei
- Price range: 550–650 EUR/month
- Rooms: 2
- Type: decomandat (separate rooms, not open-plan)
- Must have: balcony
- Scrape interval: every 15 minutes

---

### Feature: Database (`database.py`)
- SQLite locally, Postgres in production (auto-detected via `DATABASE_URL`)
- `Listing` model stores: title, price, area (sqm), rooms, floor, neighborhood, URL, image, description, source site, seen/favorite/hidden flags, first/last seen timestamps
- `init_db()` creates tables if they don't exist

---

### Feature: Scrapers (`scrapers/`)
- `base.py` — shared polite HTTP fetcher: rotates user-agent strings, adds random delay between requests, handles errors gracefully
- `imobiliare.py` — scrapes imobiliare.ro: parses listing cards, extracts price/area/rooms/floor/neighborhood, deduplicates by URL
- `storia.py` — scrapes storia.ro: same approach for that site's HTML structure

---

### Feature: Flask dashboard (`app.py` + `templates/` + `static/`)
- Shows all matching listings in a responsive card grid
- Filters: by neighborhood, min/max price, min area, rooms — applied client-side without page reload
- Per-listing actions: **Favorite** (pin to top), **Hide** (remove from view)
- Status bar: shows last scrape time, total listings found
- Background scheduler (APScheduler) runs scrapers every 15 min in a thread
- Manual "Scan now" button triggers an immediate scrape

**UI:**
- Dark mode design
- Responsive grid (1–3 columns depending on screen width)
- Each card: photo, price, area, rooms, floor, neighborhood, source badge, link to original listing

---

### Feature: Deployment config
- `Procfile` — gunicorn entry point for Railway/Heroku
- `.env.example` — documents required environment variables (`DATABASE_URL`, `SECRET_KEY`, `PORT`)
- `railway.json` — Railway-specific build/deploy config (nixpacks builder, restart policy)
- `requirements.txt` — includes `psycopg2-binary` for Postgres support

---

### Bug fix / production hardening
- `init_db()` now called at module level in `app.py` so gunicorn creates tables on first import (without this, the DB would be empty until the first request)
- `database.py` rewrites `postgres://` → `postgresql://` at runtime, since Railway emits the old prefix but SQLAlchemy 2.x requires the new one

---

### How to deploy (Railway)
1. Login to [railway.app](https://railway.app) with GitHub
2. New Project → Deploy from GitHub repo → select this repo, branch `claude/apartment-rental-scout-Fc3eO`
3. Add a PostgreSQL database service inside the project
4. In the web service Variables: add `DATABASE_URL` (reference from Postgres service) and `SECRET_KEY`
5. Railway auto-builds and gives a public URL — site is live

---

_Last updated: 2026-02-23_
