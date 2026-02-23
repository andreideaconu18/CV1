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

## 2026-02-23 — Debug tooling + scraper diagnostics

### Feature: `/debug` endpoint (`app.py`)
- JSON endpoint returning DB counts, per-source stats, last 10 listings, last run stats
- Used by the frontend debug modal to display live diagnostics

### Feature: `/debug/fetch` endpoint (`app.py`)
- Fetches one page from each site and returns HTML size, card count, bot-detection status
- Distinguishes between: blocked by bot-challenge, network error, 0 cards found (selector mismatch), and OK

### Feature: Debug modal (`templates/index.html`)
- Button in header opens a modal with per-source diagnosis
- Shows: pages fetched, cards found, area-filtered count, new vs already-known
- Displays "BLOCKED", "NETWORK ERROR", "NO PAGES", or "0 CARDS" vs "OK" per source
- Auto-polls `/debug` every 4s while a scrape is running; reloads page when done

### Improvement: Scrape status visibility (`templates/index.html`, `static/style.css`)
- Last scan time shown as relative ("3 min ago") rather than absolute timestamp
- Live spinner animation while scrape is in progress
- Page auto-reloads when scrape completes

### Bug fix: Scheduler startup (`app.py`)
- Fixed scheduler not starting reliably under gunicorn; `_start_scheduler()` now called at module import level
- Exposes actual fetch error messages in debug modal instead of generic failure label

### Bug fix: imobiliare.ro URL
- Fixed incorrect URL path (was missing `/inchirieri-apartamente/` prefix)

---

## 2026-02-23 — Confirmed working search URLs

### Change: imobiliare.ro search URL (`scrapers/imobiliare.py`)
- **Before:** `/inchirieri-apartamente/bucuresti/?nr-camere=2&pret-min=550&pret-max=650&moneda=EUR&tip-compartimentare=decomandat&an-constructie-min=1980&balcon=da`
- **After:** `/inchirieri-apartamente/2-camere?price=550-650&comfort=1,luxury`
- Year filter removed — imobiliare.ro has no year-built search param; year is extracted from listing text when available, stored as `null` if not found
- Balcony filter removed from URL — agents frequently forget to tick it, causing valid listings to be missed; balcony is now detected by scanning the description text (`"balcon" in details_text`)
- `comfort=1,luxury` covers both confort 1 (standard) and lux apartments

### Change: storia.ro search URL (`scrapers/storia.py`)
- **Before:** `/inchiriere/apartament/2-camere/bucuresti/?priceMin=...&builtYearMin=1980&buildingType=APARTMENT&ownership=decomandat&hasGarage=0`
- **After:** `/ro/rezultate/inchiriere/apartament,2-camere/bucuresti?limit=36&priceMin=550&priceMax=650&buildYearMin=1979&by=DEFAULT&direction=DESC`
- Corrected base path (`/ro/rezultate/` prefix, `apartament,2-camere` format)
- Added `limit=36` and `by=DEFAULT&direction=DESC` sort order
- Removed non-functional params (`currency`, `roomsNumber`, `buildingType`, `ownership`, `hasGarage`)

### Change: `config.py`
- `year_min` updated from `1980` to `1979` to match storia's `buildYearMin` param

---

_Last updated: 2026-02-23_
