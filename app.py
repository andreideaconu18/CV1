"""Flask web dashboard + APScheduler background scraper."""

import datetime
import logging
import threading

from flask import Flask, jsonify, redirect, render_template, request, url_for
from sqlalchemy import func

from config import PORT, REQUEST_TIMEOUT, SCRAPE_INTERVAL_MINUTES, SEARCH_CRITERIA, TARGET_AREA, TARGET_NEIGHBORHOODS
from database import Listing, SessionLocal, init_db, migrate_db
from scrapers import ImobiliareScraper, StoriaScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Ensure tables exist and schema is up to date when gunicorn imports this module
init_db()
migrate_db()

_last_scan: datetime.datetime | None = None
_last_error: str | None = None
_scrape_lock = threading.Lock()
_last_run_stats: dict = {}  # keyed by source name


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def _check_active_listings_404(db):
    """HEAD-check every active listing; mark any 404 as inactive."""
    import requests as _req
    active = db.query(Listing).filter(Listing.is_active == True).all()
    if not active:
        return
    logger.info(f"404-checking {len(active)} active listing(s)…")
    session = _req.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    for listing in active:
        try:
            resp = session.head(listing.url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if resp.status_code == 404:
                listing.is_active = False
                logger.info(f"Listing {listing.id} returned 404, marked inactive.")
        except Exception as e:
            logger.debug(f"Could not HEAD-check {listing.url}: {e}")
    db.commit()


def run_scrapers():
    global _last_scan, _last_error, _last_run_stats
    if not _scrape_lock.acquire(blocking=False):
        logger.info("Scrape already in progress, skipping.")
        return
    try:
        logger.info("Starting scrape cycle…")
        scrapers = [ImobiliareScraper(), StoriaScraper()]
        db = SessionLocal()
        run_stats = {}
        try:
            for scraper in scrapers:
                src = scraper.SOURCE_NAME
                stats = {"raw": 0, "pages_ok": 0, "pages_blocked": 0, "pages_failed": 0,
                         "area_filtered": 0, "already_known": 0, "new": 0, "error": None}
                run_stats[src] = stats
                try:
                    listings = scraper.scrape()
                except Exception as e:
                    stats["error"] = str(e)
                    _last_error = f"{src}: {e}"
                    logger.error(f"{src} scraper failed: {e}")
                    continue

                stats["raw"] = len(listings)
                stats["pages_ok"] = scraper.fetch_stats["pages_ok"]
                stats["pages_blocked"] = scraper.fetch_stats["pages_blocked"]
                stats["pages_failed"] = scraper.fetch_stats["pages_failed"]
                stats["fetch_error"] = scraper.fetch_stats["last_error"]
                for listing in listings:
                    if not listing.matches_area(TARGET_AREA, TARGET_NEIGHBORHOODS):
                        stats["area_filtered"] += 1
                        continue
                    existing = (
                        db.query(Listing)
                        .filter_by(external_id=listing.external_id)
                        .first()
                    )
                    if existing:
                        existing.last_seen = datetime.datetime.utcnow()
                        existing.is_active = True
                        if listing.floor is not None:
                            existing.floor = listing.floor
                        if listing.extra_images is not None:
                            existing.extra_images = listing.extra_images
                        stats["already_known"] += 1
                    else:
                        db.add(listing)
                        stats["new"] += 1

            db.commit()
            _check_active_listings_404(db)
            _last_scan = datetime.datetime.utcnow()
            _last_run_stats = run_stats
            total_new = sum(s["new"] for s in run_stats.values())
            total_filtered = sum(s["area_filtered"] for s in run_stats.values())
            logger.info(f"Scrape done. {total_new} new listings added. {total_filtered} filtered by area.")
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


# Start scheduler when module is imported (covers gunicorn + direct run)
_start_scheduler()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _relative_time(dt):
    if dt is None:
        return "never"
    delta = datetime.datetime.utcnow() - dt
    minutes = int(delta.total_seconds() / 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    return f"{hours}h ago"


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

    last_scan_str = _relative_time(_last_scan)

    return {
        "total": total,
        "new_today": new_today,
        "favorites": favorites,
        "hidden": hidden,
        "last_scan": last_scan_str,
        "scrape_running": _scrape_lock.locked(),
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
    scraping_now = _scrape_lock.locked()
    if not scraping_now:
        threading.Thread(target=run_scrapers, daemon=True).start()
    return redirect(url_for("index", scraping=1))


@app.route("/debug")
def debug():
    """Debug endpoint: raw DB counts + scraper state."""
    db = SessionLocal()
    try:
        total = db.query(func.count(Listing.id)).scalar()
        active = db.query(func.count(Listing.id)).filter_by(is_active=True).scalar()
        by_source = {
            "imobiliare": db.query(func.count(Listing.id)).filter_by(source="imobiliare").scalar(),
            "storia": db.query(func.count(Listing.id)).filter_by(source="storia").scalar(),
        }
        recent = [
            {"id": l.id, "source": l.source, "title": l.title,
             "neighborhood": l.neighborhood, "price": l.price,
             "first_seen": l.first_seen.isoformat() if l.first_seen else None}
            for l in db.query(Listing).order_by(Listing.first_seen.desc()).limit(10).all()
        ]
    finally:
        db.close()
    return jsonify({
        "last_scan": _last_scan.isoformat() if _last_scan else None,
        "scrape_running": _scrape_lock.locked(),
        "last_error": _last_error,
        "total_in_db": total,
        "active": active,
        "by_source": by_source,
        "recent_10": recent,
        "last_run_stats": _last_run_stats,
    })


@app.route("/debug/fetch")
def debug_fetch():
    """Fetch one page from each site and return an HTML preview to diagnose blocking/JS issues."""
    import re as _re
    from scrapers.imobiliare import _build_search_url as imob_url
    from scrapers.storia import _build_search_url as storia_url
    from scrapers.base import BaseScraper

    scraper = BaseScraper()
    results = {}

    for name, url in [("imobiliare", imob_url(1)), ("storia", storia_url(1))]:
        try:
            soup = scraper.fetch_page(url)
            if soup is None:
                results[name] = {"url": url, "status": "blocked_or_failed", "html_preview": None}
            else:
                text = soup.get_text(" ", strip=True)
                cards_imob = len(soup.select("div.ilu-card, article.ilu-card, div[class*='card-']"))
                cards_storia = len(soup.select("article[data-cy='listing-item'], article.css-1id4k1, div[data-testid='listing-item']"))
                all_articles = len(soup.find_all("article"))

                # Collect unique classes from article/li/div tags for selector diagnosis
                tag_classes = {}
                for tag in soup.find_all(["article", "li", "section"]):
                    cls = tag.get("class")
                    if cls:
                        key = f"{tag.name}.{' '.join(cls)}"
                        tag_classes[key] = tag_classes.get(key, 0) + 1
                # Also find all /anunt/ links and their immediate parent classes
                anunt_links = soup.find_all("a", href=_re.compile(r"/anunt/"))
                anunt_parent_classes = []
                for a in anunt_links[:5]:
                    p = a.find_parent(["article", "li", "div", "section"])
                    if p:
                        anunt_parent_classes.append({
                            "tag": p.name,
                            "class": p.get("class"),
                            "href": a.get("href", "")[:80],
                        })

                results[name] = {
                    "url": url,
                    "status": "ok",
                    "html_bytes": len(soup.encode()),
                    "cards_matched": cards_imob if name == "imobiliare" else cards_storia,
                    "total_articles": all_articles,
                    "anunt_links_found": len(anunt_links),
                    "anunt_parent_classes": anunt_parent_classes,
                    "article_li_classes": dict(sorted(tag_classes.items(), key=lambda x: -x[1])[:20]),
                    "text_preview": text[:500],
                }
        except Exception as e:
            results[name] = {"url": url, "status": f"error: {e}"}

    return jsonify(results)


@app.route("/debug/floor")
def debug_floor():
    """Show raw card text around 'etaj' and what floor value gets extracted, for diagnosis."""
    import re as _re
    from scrapers.imobiliare import _build_search_url as imob_url
    from scrapers.storia import _build_search_url as storia_url
    from scrapers.base import BaseScraper

    scraper = BaseScraper()
    results = {}

    for name, url, card_sel, link_pat in [
        ("imobiliare", imob_url(1),
         "div.ilu-card, article.ilu-card, div[class*='card-']", r"/anunt/"),
        ("storia", storia_url(1),
         "article[data-cy='listing-item'], article.css-1id4k1, div[data-testid='listing-item']",
         r"/ro/oferta/|/oferta/"),
    ]:
        try:
            soup = scraper.fetch_page(url)
            if soup is None:
                results[name] = {"status": "blocked_or_failed"}
                continue

            cards = soup.select(card_sel)
            if not cards:
                cards = list({
                    a.find_parent("article") or a.find_parent("li") or a.find_parent("div")
                    for a in soup.find_all("a", href=_re.compile(link_pat))
                    if a.find_parent("article") or a.find_parent("li")
                } - {None})

            card_data = []
            for card in cards[:6]:
                text = card.get_text(" ", strip=True).lower()
                # Show the 120 chars around first "etaj" mention
                idx = text.find("etaj")
                snippet = text[max(0, idx - 20):idx + 100] if idx != -1 else "(no 'etaj' in text)"
                # Run floor extraction
                floor = None
                fm = _re.search(r"etaj(?:ul)?\s*[:\s]*(\d+(?:\s*(?:/|din)\s*\d+)?)", text)
                if fm:
                    raw = fm.group(1).strip()
                    floor = _re.sub(r"\s*din\s*", "/", raw).replace(" ", "")
                elif _re.search(r"\bparter\b", text):
                    floor = "parter"
                card_data.append({"etaj_snippet": snippet, "extracted_floor": floor})

            results[name] = {"status": "ok", "cards_found": len(cards), "sample": card_data}
        except Exception as e:
            results[name] = {"status": f"error: {e}"}

    return jsonify(results)


@app.route("/debug/detail")
def debug_detail():
    """Fetch a listing's detail page and show what each floor-extraction pattern sees.

    Pass ?url=<listing-url> or leave blank to use the first storia listing in DB.
    """
    import re as _re
    from scrapers.base import BaseScraper

    url = request.args.get("url")
    if not url:
        db = SessionLocal()
        try:
            row = db.query(Listing).filter_by(source="storia").first()
            url = row.url if row else None
        finally:
            db.close()
    if not url:
        return jsonify({"error": "No URL provided and no listings in DB"})

    scraper = BaseScraper()
    soup = scraper.fetch_page(url)
    if not soup:
        return jsonify({"url": url, "status": "blocked_or_failed"})

    page_text = soup.get_text(" ", strip=True).lower()

    # All snippets around "etaj" in visible text
    snippets = []
    for hit in _re.finditer(r"etaj", page_text):
        s, e = max(0, hit.start() - 15), min(len(page_text), hit.end() + 100)
        snippets.append(page_text[s:e])

    m1 = _re.search(r"etaj(?:ul)?\s*[:\s]*(\d+)\s*(?:din|/)\s*(\d+)", page_text)
    m2 = _re.search(r"etaj[^\d>]*>\s*(\d+)\s*(?:din|/)\s*(\d+)", page_text)

    json_floor = None
    for script in soup.find_all("script"):
        s = script.string or ""
        if not s:
            continue
        sm = _re.search(
            r'"[^"]*(?:etaj|floor)[^"]*"\s*:\s*"(\d+)\s*(?:/|din)\s*(\d+)"',
            s, _re.IGNORECASE,
        )
        if sm:
            json_floor = f"{sm.group(1)}/{sm.group(2)}"
            break

    return jsonify({
        "url": url,
        "status": "ok",
        "etaj_snippets_in_text": snippets[:15],
        "pattern1_standard": f"{m1.group(1)}/{m1.group(2)}" if m1 else None,
        "pattern2_gt_notation": f"{m2.group(1)}/{m2.group(2)}" if m2 else None,
        "pattern3_json_script": json_floor,
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
