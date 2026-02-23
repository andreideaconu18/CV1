"""Flask web dashboard + APScheduler background scraper."""

import datetime
import logging
import threading

from flask import Flask, jsonify, redirect, render_template, request, url_for
from sqlalchemy import func

from config import PORT, SCRAPE_INTERVAL_MINUTES, SEARCH_CRITERIA, TARGET_AREA, TARGET_NEIGHBORHOODS
from database import Listing, SessionLocal, init_db
from scrapers import ImobiliareScraper, StoriaScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Ensure tables exist when gunicorn imports this module
init_db()

_last_scan: datetime.datetime | None = None
_scrape_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def run_scrapers():
    global _last_scan
    if not _scrape_lock.acquire(blocking=False):
        logger.info("Scrape already in progress, skipping.")
        return
    try:
        logger.info("Starting scrape cycle…")
        scrapers = [ImobiliareScraper(), StoriaScraper()]
        db = SessionLocal()
        try:
            new_count = 0
            for scraper in scrapers:
                try:
                    listings = scraper.scrape()
                except Exception as e:
                    logger.error(f"{scraper.SOURCE_NAME} scraper failed: {e}")
                    continue

                for listing in listings:
                    # Area filter
                    if not listing.matches_area(TARGET_AREA, TARGET_NEIGHBORHOODS):
                        continue
                    existing = (
                        db.query(Listing)
                        .filter_by(external_id=listing.external_id)
                        .first()
                    )
                    if existing:
                        existing.last_seen = datetime.datetime.utcnow()
                        existing.is_active = True
                    else:
                        db.add(listing)
                        new_count += 1

            db.commit()
            _last_scan = datetime.datetime.utcnow()
            logger.info(f"Scrape done. {new_count} new listings added.")
        finally:
            db.close()
    finally:
        _scrape_lock.release()


def _start_scheduler():
    import time
    interval_seconds = SCRAPE_INTERVAL_MINUTES * 60

    def loop():
        run_scrapers()  # run immediately on startup
        while True:
            time.sleep(interval_seconds)
            run_scrapers()

    t = threading.Thread(target=loop, daemon=True, name="scraper-thread")
    t.start()
    logger.info(f"Scraper scheduled every {SCRAPE_INTERVAL_MINUTES} min.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_stats(db):
    today = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    total = db.query(func.count(Listing.id)).filter_by(is_active=True, is_hidden=False).scalar()
    new_today = (
        db.query(func.count(Listing.id))
        .filter(Listing.first_seen >= today, Listing.is_active == True, Listing.is_hidden == False)
        .scalar()
    )
    favorites = db.query(func.count(Listing.id)).filter_by(is_favorite=True, is_active=True).scalar()
    hidden = db.query(func.count(Listing.id)).filter_by(is_hidden=True).scalar()

    if _last_scan:
        last_scan_str = _last_scan.strftime("%H:%M")
    else:
        last_scan_str = "never"

    return {
        "total": total,
        "new_today": new_today,
        "favorites": favorites,
        "hidden": hidden,
        "last_scan": last_scan_str,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    filter_val = request.args.get("filter", "all")
    db = SessionLocal()
    try:
        query = db.query(Listing)

        if filter_val == "new":
            today = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            query = query.filter(Listing.first_seen >= today, Listing.is_active == True, Listing.is_hidden == False)
        elif filter_val == "favorites":
            query = query.filter_by(is_favorite=True, is_active=True)
        elif filter_val == "hidden":
            query = query.filter_by(is_hidden=True)
        elif filter_val == "imobiliare":
            query = query.filter_by(source="imobiliare", is_active=True, is_hidden=False)
        elif filter_val == "storia":
            query = query.filter_by(source="storia", is_active=True, is_hidden=False)
        else:
            query = query.filter_by(is_active=True, is_hidden=False)

        listings = query.order_by(Listing.first_seen.desc()).all()
        stats = _get_stats(db)
    finally:
        db.close()

    return render_template(
        "index.html",
        listings=listings,
        stats=stats,
        filter=filter_val,
        interval=SCRAPE_INTERVAL_MINUTES,
    )


@app.route("/api/listing/<int:listing_id>/favorite", methods=["POST"])
def toggle_favorite(listing_id):
    db = SessionLocal()
    try:
        listing = db.query(Listing).get(listing_id)
        if not listing:
            return jsonify({"error": "not found"}), 404
        listing.is_favorite = not listing.is_favorite
        db.commit()
        return jsonify({"is_favorite": listing.is_favorite})
    finally:
        db.close()


@app.route("/api/listing/<int:listing_id>/hide", methods=["POST"])
def toggle_hidden(listing_id):
    db = SessionLocal()
    try:
        listing = db.query(Listing).get(listing_id)
        if not listing:
            return jsonify({"error": "not found"}), 404
        listing.is_hidden = not listing.is_hidden
        db.commit()
        return jsonify({"is_hidden": listing.is_hidden})
    finally:
        db.close()


@app.route("/scrape")
def trigger_scrape():
    """Manual scrape trigger."""
    threading.Thread(target=run_scrapers, daemon=True).start()
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    _start_scheduler()
    app.run(host="0.0.0.0", port=PORT, debug=False)
