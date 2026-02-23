"""Scraper for imobiliare.ro."""

import logging
import re

from config import SEARCH_CRITERIA
from database import Listing
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.imobiliare.ro"


def _build_search_url(page=1):
    c = SEARCH_CRITERIA
    # /inchirieri-apartamente/2-camere?price=550-650&comfort=1,luxury
    # Note: imobiliare.ro has no year-built filter in search URL — year is extracted
    # from each listing's text. Balcony filter omitted intentionally: agents often
    # forget to tick it, so we detect balcony from description text instead.
    url = f"{BASE_URL}/inchirieri-apartamente/{c['rooms']}-camere"
    params = (
        f"?price={c['price_min']}-{c['price_max']}"
        f"&comfort=1,luxury"
        f"&pagina={page}"
    )
    return url + params


class ImobiliareScraper(BaseScraper):
    SOURCE_NAME = "imobiliare"

    def scrape(self):
        listings = []
        page = 1
        while True:
            url = _build_search_url(page)
            logger.info(f"Fetching imobiliare.ro page {page}: {url}")
            soup = self.fetch_page(url)
            if soup is None:
                break

            cards = soup.select("div.ilu-card, article.ilu-card, div[class*='card-']")
            # Fallback: any <article> with a link to /anunt/
            if not cards:
                cards = [
                    a.find_parent("article") or a.find_parent("div")
                    for a in soup.find_all("a", href=re.compile(r"/anunt/"))
                    if a.find_parent("article") or a.find_parent("div")
                ]
                # deduplicate
                seen = set()
                unique = []
                for c in cards:
                    if c and id(c) not in seen:
                        seen.add(id(c))
                        unique.append(c)
                cards = unique

            if not cards:
                logger.info(f"No cards found on page {page}, stopping.")
                break

            for card in cards:
                listing = self._parse_card(card)
                if listing:
                    listings.append(listing)

            # Check for next page
            next_btn = soup.select_one("a[rel='next'], .paginare a.urmator, li.next a")
            if not next_btn:
                break
            page += 1
            if page > 20:  # safety cap
                break

        logger.info(f"imobiliare.ro: found {len(listings)} listings")
        return listings

    def _parse_card(self, card):
        try:
            # URL + external_id
            link = card.find("a", href=re.compile(r"/anunt/"))
            if not link:
                return None
            href = link["href"]
            if not href.startswith("http"):
                href = BASE_URL + href
            m = re.search(r"/anunt/([^/?#]+)", href)
            if not m:
                return None
            external_id = m.group(1)

            # Title
            title_el = card.select_one(
                "h2, h3, .title-anunt, [class*='titlu'], [class*='title']"
            )
            title = title_el.get_text(strip=True) if title_el else None

            # Details blob (needed for price fallback too)
            details_text = card.get_text(" ", strip=True).lower()

            # Price — try targeted selector first, then regex on full card text
            price, currency = None, "EUR"
            price_el = card.select_one(
                "[class*='pret'], [class*='price'], .pret-anunt"
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
                # Fallback: scan full card text. Use \b so "79 m² 600 €" matches
                # 600, not 9600 (old greedy pattern grabbed "9" from "79").
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

            # Floor — "etaj 3", "etaj: 3", "etaj3" all handled
            floor = None
            fm = re.search(r"etaj[\s:]*(\w+)", details_text)
            if fm:
                floor = fm.group(1)

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
            has_balcony = "balcon" in details_text

            # Neighborhood / address
            neighborhood, address = None, None
            loc_el = card.select_one(
                "[class*='locali'], [class*='adresa'], [class*='zona'], [class*='location']"
            )
            if loc_el:
                loc_text = loc_el.get_text(" ", strip=True)
                parts = [p.strip() for p in loc_text.split(",")]
                if parts:
                    neighborhood = parts[-1] if len(parts) > 1 else parts[0]
                    address = ", ".join(parts[:-1]) if len(parts) > 1 else None

            # Image
            image_url = None
            img = card.find("img")
            if img:
                image_url = img.get("src") or img.get("data-src") or img.get("data-lazy-src")

            return Listing(
                external_id=external_id,
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
            )
        except Exception as e:
            logger.warning(f"Failed to parse imobiliare card: {e}")
            return None
