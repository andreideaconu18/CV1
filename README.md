# Apartment Rental Scout

A self-hosted web application that automatically scrapes Romanian real-estate websites and aggregates apartment rental listings into a unified dashboard. Built for finding apartments in Bucharest with customizable search criteria.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3, Flask 3.1 |
| ORM | SQLAlchemy 2.0 |
| Scraping | BeautifulSoup4, lxml, Requests |
| Scheduling | APScheduler (background thread) |
| Database | SQLite (local) / PostgreSQL (production) |
| Frontend | Vanilla JS, HTML5, CSS3 (dark theme) |
| Deployment | Gunicorn, Railway, Nixpacks |

## Project Structure

```
├── app.py                 # Flask routes, scheduler, scraper orchestration
├── config.py              # Search criteria, target area, scraping settings
├── database.py            # SQLAlchemy models and DB initialization
├── scrapers/
│   ├── base.py            # BaseScraper — shared HTTP fetching, parsing, retry logic
│   ├── imobiliare.py      # Scraper for imobiliare.ro
│   └── storia.py          # Scraper for storia.ro
├── templates/
│   └── index.html         # Dashboard UI (filters, listing cards, debug modal)
├── static/
│   └── style.css          # Dark-themed responsive styling
├── Procfile               # Gunicorn startup command
├── railway.json           # Railway build & deploy config
└── requirements.txt       # Python dependencies
```

## Features

### Dashboard
- Responsive card grid layout (1-3 columns)
- Image slider with gallery collage
- Filter by: All, New Today, Favorites, Hidden, Source
- Star/hide actions per listing
- Metadata badges (source, age, rooms, floor, balcony, year, surface)
- Manual "Scan now" button and debug modal

### Scraping Engine
- Dual-source scraping: **imobiliare.ro** and **storia.ro**
- Automated background runs on a configurable interval (default 120 min)
- Multi-page pagination (up to 20 pages per source)
- Detail-page enrichment for floor info and gallery images
- 404 checking to detect removed listings
- Polite scraping: random delays, user-agent rotation, bot-detection (Cloudflare)
- Thread-safe execution via lock

### Search Configuration

Search criteria are defined in `config.py`:

```python
SEARCH_CRITERIA = {
    "city": "bucuresti",
    "rooms": 2,
    "price_min": 550,
    "price_max": 650,
    "currency": "EUR",
    "layout": "decomandat",
    "year_min": 1979,
    "balcony": True,
}
```

A geographic bounding box and neighborhood whitelist further filter results to central Bucharest.

## Setup

### Local Development

1. Clone the repo and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and configure environment variables.
3. Run the app:
   ```bash
   python app.py
   ```
   The app uses a local SQLite database by default.

### Production (Railway)

- Provision a PostgreSQL database on Railway.
- Set environment variables: `DATABASE_URL`, `SECRET_KEY`, `PORT`, `SCRAPE_INTERVAL`.
- Deploy — Railway uses the `Procfile` to start Gunicorn with 1 worker and 4 threads.

## Architecture Notes

- **Template Method pattern** — `BaseScraper` defines the scraping flow; subclasses implement `_parse_card()`.
- **Deduplication** — Listings are keyed by `external_id` (storia IDs prefixed with `"storia_"`).
- **Listing states** — `is_active` (404-checked), `is_favorite`, `is_hidden`, with `first_seen`/`last_seen` timestamps.
- **Lightweight migrations** — `migrate_db()` applies ALTER TABLE statements safely, allowing partial success.
- **Auto-detects DB driver** — Converts `postgres://` to `postgresql://` for SQLAlchemy 2.x compatibility.
