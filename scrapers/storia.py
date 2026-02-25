"""Scraper for storia.ro."""

import json
import logging
import re

from config import SEARCH_CRITERIA
from database import Listing
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.storia.ro"


def _build_search_url(page=1):
    c = SEARCH_CRITERIA
    # storia uses /ro/rezultate/inchiriere/apartament,2-camere/bucuresti style paths
    url = (
        f"{BASE_URL}/ro/rezultate/inchiriere/apartament,{c['rooms']}-camere/{c['city']}"
        f"?limit=36"
        f"&priceMin={c['price_min']}"
        f"&priceMax={c['price_max']}"
        f"&buildYearMin={c['year_min']}"
        f"&by=DEFAULT&direction=DESC"
        f"&page={page}"
    )
    return url


def _floor_from_listing_obj(obj):
    """Extract floor string from a single listing dict from __NEXT_DATA__."""
    if not isinstance(obj, dict):
        return None

    # OLX-style params array: [{"key": "m_floor", "value": {"label": "5"}}, ...]
    params = obj.get("params") or obj.get("parameters") or []
    if isinstance(params, list):
        floor_val = None
        floor_count = None
        for p in params:
            if not isinstance(p, dict):
                continue
            key = (p.get("key") or "").lower()
            v = p.get("value")
            label = None
            if isinstance(v, dict):
                label = v.get("label") or v.get("key") or ""
            elif isinstance(v, (str, int)):
                label = str(v)
            if key in ("m_floor", "floor", "etaj"):
                floor_val = str(label).strip() if label is not None else None
            elif key in ("m_floor_count", "floor_count", "nr_floors", "etaje"):
                floor_count = str(label).strip() if label is not None else None
        if floor_val and floor_count:
            return f"{floor_val}/{floor_count}"
        if floor_val:
            return floor_val

    # Direct string "X/Y" or "parter/Y"
    for key in ("floor", "etaj", "floorInfo", "floorLabel"):
        val = obj.get(key)
        if val and isinstance(val, str) and "/" in val:
            return val

    # Separate numeric fields
    floor_num = obj.get("floorNumber") or obj.get("floor_number")
    total_floors = (
        obj.get("numberOfFloors") or obj.get("total_floors") or obj.get("floorCount")
    )
    if floor_num is not None and total_floors is not None:
        return f"{floor_num}/{total_floors}"

    return None


def extract_next_data_floors(soup):
    """Parse __NEXT_DATA__ JSON and return {slug -> floor_str} for all listings."""
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return {}

    try:
        data = json.loads(script.string)
    except (json.JSONDecodeError, ValueError):
        return {}

    floors = {}

    def _scan(obj):
        if isinstance(obj, list):
            for item in obj:
                _scan(item)
        elif isinstance(obj, dict):
            slug = obj.get("slug") or obj.get("id") or obj.get("externalId")
            if slug:
                floor_str = _floor_from_listing_obj(obj)
                if floor_str:
                    floors[str(slug)] = floor_str
            for v in obj.values():
                _scan(v)

    _scan(data)
    return floors


class StoriaScraper(BaseScraper):
    SOURCE_NAME = "storia"

    def scrape(self):
        listings = []
        page = 1
        while True:
            url = _build_search_url(page)
            logger.info(f"Fetching storia.ro page {page}: {url}")
            soup = self.fetch_page(url)
            if soup is None:
                break

            # Extract floor data from __NEXT_DATA__ (already fetched, no extra requests)
            page_floors = extract_next_data_floors(soup)
            logger.info(f"storia.ro page {page}: extracted floors for {len(page_floors)} listings from __NEXT_DATA__")

            # storia.ro renders listing cards as <article> or divs with data-id
            cards = soup.select(
                "article[data-cy='listing-item'], article.css-1id4k1, div[data-testid='listing-item']"
            )
            if not cards:
                # fallback: articles containing /ro/oferta/ links
                cards = list({
                    a.find_parent("article") or a.find_parent("li")
                    for a in soup.find_all("a", href=re.compile(r"/ro/oferta/|/oferta/"))
                    if a.find_parent("article") or a.find_parent("li")
                } - {None})

            if not cards:
                logger.info(f"No cards found on storia page {page}, stopping.")
                break

            for card in cards:
                listing = self._parse_card(card, page_floors)
                if listing:
                    listings.append(listing)

            # Pagination: look for rel=next or a page N+1 link
            next_btn = soup.select_one(
                "a[data-cy='pagination.next-page'], a[rel='next'], li.next > a"
            )
            if not next_btn:
                break
            page += 1
            if page > 20:
                break

        logger.info(f"storia.ro: found {len(listings)} listings")
        return listings

    def _parse_card(self, card, page_floors=None):
        try:
            # URL + external_id
            link = card.find(
                "a", href=re.compile(r"/ro/oferta/|/oferta/|/anunt/")
            )
            if not link:
                # try any <a> inside the card
                link = card.find("a", href=True)
            if not link:
                return None
            href = link["href"]
            if not href.startswith("http"):
                href = BASE_URL + href
            # external id: last path segment before query
            m = re.search(r"/([A-Za-z0-9_-]+)(?:\?|$)", href)
            external_id = m.group(1) if m else href

            # Title
            title_el = card.select_one(
                "h3, h2, [data-cy='listing-item-title'], [class*='title'], [class*='Title']"
            )
            title = title_el.get_text(strip=True) if title_el else None

            details_text = card.get_text(" ", strip=True).lower()

            # Price — try targeted selector first, then regex on full card text
            price, currency = None, "EUR"
            price_el = card.select_one(
                "[data-cy='listing-item-price'], [class*='price'], [class*='Price'], [class*='pret']"
            )
            if price_el:
                raw = price_el.get_text(strip=True)
                nums = re.findall(r"[\d\s]+", raw)
                if nums:
                    try:
                        price = float("".join(nums[0].split()))
                    except ValueError:
                        pass
                if "EUR" in raw.upper():
                    currency = "EUR"
                elif "RON" in raw.upper() or "LEI" in raw.upper():
                    currency = "RON"
            if price is None:
                pm = re.search(r'\b(\d{3,5})\s*(?:€|eur\b)', details_text)
                if pm:
                    try:
                        price = float(pm.group(1))
                    except ValueError:
                        pass
                else:
                    pm = re.search(r'\b(\d{4,6})\s*(?:ron|lei)\b', details_text)
                    if pm:
                        try:
                            price = float(pm.group(1))
                            currency = "RON"
                        except ValueError:
                            pass

            # Rooms
            rooms = None
            rm = re.search(r"(\d)\s*camere?", details_text)
            if rm:
                rooms = int(rm.group(1))

            # Surface
            surface = None
            sm = re.search(r"(\d+(?:[.,]\d+)?)\s*m[²2]", details_text)
            if sm:
                try:
                    surface = float(sm.group(1).replace(",", "."))
                except ValueError:
                    pass

            # Floor — try __NEXT_DATA__ JSON first, then card text
            floor = page_floors.get(external_id) if page_floors else None
            if not floor:
                fm = re.search(r"etaj(?:ul)?\s*[:\s]*(\d+(?:\s*(?:/|din)\s*\d+)?)", details_text)
                if fm:
                    raw_floor = fm.group(1).strip()
                    floor = re.sub(r"\s*din\s*", "/", raw_floor).replace(" ", "")
                elif re.search(r"\bparter\b", details_text):
                    floor = "parter"

            # Year built
            year_built = None
            ym = re.search(r"an\s*(?:constructie|construc[tț]ie)[:\s]*(\d{4})", details_text)
            if not ym:
                ym = re.search(r"\b(19[89]\d|20[012]\d)\b", details_text)
            if ym:
                year_built = int(ym.group(1))

            # Layout
            layout = None
            if "decomandat" in details_text:
                layout = "decomandat"
            elif "semidecomandat" in details_text:
                layout = "semidecomandat"

            # Balcony
            has_balcony = "balcon" in details_text or "terasa" in details_text

            # Neighborhood
            neighborhood, address = None, None
            loc_el = card.select_one(
                "[data-cy='listing-item-address'], [class*='location'], [class*='Location'], "
                "[class*='adresa'], [class*='zona']"
            )
            if loc_el:
                loc_text = loc_el.get_text(" ", strip=True)
                parts = [p.strip() for p in loc_text.split(",")]
                if parts:
                    neighborhood = parts[-1] if len(parts) > 1 else parts[0]
                    address = ", ".join(parts[:-1]) if len(parts) > 1 else None

            # Image (card thumbnail)
            image_url = None
            img = card.find("img")
            if img:
                image_url = img.get("src") or img.get("data-src") or img.get("data-lazy-src")

            # Fetch detail page for gallery images (floor enrichment only if not from JSON)
            floor, extra_images = self._fetch_detail_info(href, floor, image_url)

            return Listing(
                external_id=f"storia_{external_id}",
                source=self.SOURCE_NAME,
                url=href,
                title=title,
                price=price,
                currency=currency,
                rooms=rooms,
                surface=surface,
                year_built=year_built,
                floor=floor,
                layout=layout,
                neighborhood=neighborhood,
                address=address,
                has_balcony=has_balcony,
                image_url=image_url,
                extra_images=extra_images,
            )
        except Exception as e:
            logger.warning(f"Failed to parse storia card: {e}")
            return None
