"""Base scraper class with common functionality."""

import logging
import random
import time

import requests
from bs4 import BeautifulSoup

from config import USER_AGENTS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


class BaseScraper:
    """Base class for apartment scrapers."""

    SOURCE_NAME = "base"

    def __init__(self):
        self.session = requests.Session()
        self._rotate_user_agent()
        self.fetch_stats = {"pages_ok": 0, "pages_blocked": 0, "pages_failed": 0, "last_error": None}

    def _rotate_user_agent(self):
        """Set a random user agent."""
        ua = random.choice(USER_AGENTS)
        self.session.headers.update({
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        })

    def fetch_page(self, url, retries=3):
        """Fetch a page with retries and polite delays."""
        for attempt in range(retries):
            try:
                self._rotate_user_agent()
                time.sleep(random.uniform(1.5, 3.5))  # polite delay
                response = self.session.get(url, timeout=REQUEST_TIMEOUT)
                logger.info(
                    f"HTTP {response.status_code} for {url} "
                    f"({len(response.content)} bytes)"
                )
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "lxml")
                # Detect bot/JS challenge pages
                body_text = soup.get_text(" ", strip=True)[:300].lower()
                if any(kw in body_text for kw in ("just a moment", "checking your browser", "enable javascript", "captcha")):
                    logger.warning(f"Bot challenge detected at {url} — scraper is blocked")
                    self.fetch_stats["pages_blocked"] += 1
                    return None
                self.fetch_stats["pages_ok"] += 1
                return soup
            except requests.RequestException as e:
                self.fetch_stats["last_error"] = str(e)
                logger.warning(f"Attempt {attempt + 1}/{retries} failed for {url}: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** (attempt + 1))
        logger.error(f"Failed to fetch {url} after {retries} attempts")
        self.fetch_stats["pages_failed"] += 1
        return None

    def _fetch_detail_info(self, url, current_floor, first_image_url=None):
        """Fetch a listing's detail page to get total floor count AND up to 4 gallery images.

        Returns (updated_floor_str, extra_images_json_str_or_None).
        """
        import re as _re
        import json as _json

        updated_floor = current_floor
        extra_imgs = []

        soup = self.fetch_page(url)
        if not soup:
            return updated_floor, None

        page_text = soup.get_text(" ", strip=True).lower()

        # Floor: prefer the detail page over the card (card may say "10+" when real is "11")
        # Only skip if the card already gave us a clean "X/Y" value.
        if not (current_floor and "/" in current_floor):
            detail_floor = None

            # ── Approach A: walk DOM for "Etaj" label → adjacent value element ──────
            # Handles any spec-table structure regardless of separator in get_text().
            for label_el in soup.find_all(
                string=_re.compile(r"^\s*etaj[ul]*:?\s*$", _re.IGNORECASE)
            ):
                parent = label_el.parent
                # Try immediate sibling of the label element, then uncle (parent's sibling)
                for candidate in (
                    parent.find_next_sibling(),
                    parent.parent.find_next_sibling() if parent.parent else None,
                ):
                    if not candidate:
                        continue
                    val = candidate.get_text(" ", strip=True)
                    vm = _re.search(r">?\s*(\d+)\s*(?:din|/)\s*(\d+)", val)
                    if vm:
                        x, y = int(vm.group(1)), int(vm.group(2))
                        if ">" in val and x + 1 == y:
                            detail_floor = f"{y}/{y}"
                        else:
                            detail_floor = f"{x}/{y}"
                        break
                    # "parter/8" or "parter din 8"
                    vm_p = _re.search(r"parter\s*(?:din|/)\s*(\d+)", val, _re.IGNORECASE)
                    if vm_p:
                        detail_floor = f"parter/{vm_p.group(1)}"
                        break
                if detail_floor:
                    break

            # ── Approach B: broad text scan on the full page text ─────────────────
            # Covers "etaj: 3/8", "etajul 3/8", "etaj 3 din 8", "etaj: > 10/11",
            # and "etaj parter/8" / "etaj parter din 8"
            if not detail_floor:
                m = _re.search(
                    r"etaj[ul: >]*(\d+)\s*(?:din|/)\s*(\d+)", page_text
                )
                if m:
                    x, y = int(m.group(1)), int(m.group(2))
                    between = page_text[m.start(): m.start(1)]
                    if ">" in between and x + 1 == y:
                        detail_floor = f"{y}/{y}"
                    else:
                        detail_floor = f"{x}/{y}"
                else:
                    mp = _re.search(
                        r"etaj[ul: >]*parter\s*(?:din|/)\s*(\d+)", page_text
                    )
                    if mp:
                        detail_floor = f"parter/{mp.group(1)}"

            # ── Approach C: JSON script data ──────────────────────────────────────
            # storia.ro / Next.js puts all page data in <script id="__NEXT_DATA__">.
            # Try both string ("floor": "3/8") and numeric ("floor": 3, "floors": 8).
            if not detail_floor:
                for script in soup.find_all("script"):
                    s = script.string or ""
                    if not s:
                        continue
                    # String value: "floorNo": "3/8"
                    sm = _re.search(
                        r'"[^"]*(?:etaj|floor)[^"]*"\s*:\s*"(\d+)\s*(?:/|din)\s*(\d+)"',
                        s, _re.IGNORECASE,
                    )
                    if sm:
                        detail_floor = f"{sm.group(1)}/{sm.group(2)}"
                        break
                    # Numeric values: "floorNumber": 3  +  "numberOfFloors": 8
                    fn = _re.search(
                        r'"(?:floor(?:Number|No|Level)?|etaj(?:ul)?)":\s*(\d+)',
                        s, _re.IGNORECASE,
                    )
                    tf = _re.search(
                        r'"(?:(?:number|total|nr)Of(?:Floors|Etaje)|(?:floors|etaje)(?:Total|Nr|Count)?)":\s*(\d+)',
                        s, _re.IGNORECASE,
                    )
                    if fn and tf:
                        detail_floor = f"{fn.group(1)}/{tf.group(1)}"
                        break

            if detail_floor:
                updated_floor = detail_floor
            elif current_floor:
                # Last resort: find total-floor count only ("total etaje: 11")
                m3 = _re.search(
                    r"(?:nr\.?\s*etaje?|num[aă]r\s*etaje?|total\s*etaje?)[:\s]*(\d+)",
                    page_text,
                )
                if m3:
                    updated_floor = f"{current_floor}/{m3.group(1)}"

        # Gallery images: try known gallery containers, fall back to all imgs
        _SKIP = ("logo", "icon", "sprite", "avatar", "flag", "badge",
                 "placeholder", "loading", "blur", "data:")

        def _is_photo(src):
            if not src or len(src) < 15 or src.startswith("data:"):
                return False
            sl = src.lower()
            return not any(x in sl for x in _SKIP)

        seen = {first_image_url} if first_image_url else set()
        source_imgs = []
        for sel in (
            "[data-cy*='gallery']", "[class*='gallery']", "[class*='Gallery']",
            "[class*='photos']", "[class*='Photos']",
            "[class*='slider']", "[class*='Slider']",
            "[data-testid*='gallery']", "[data-testid*='photo']",
        ):
            container = soup.select_one(sel)
            if container:
                source_imgs = container.find_all("img")
                break
        if not source_imgs:
            source_imgs = soup.find_all("img")

        for img_tag in source_imgs:
            src = (img_tag.get("src") or img_tag.get("data-src")
                   or img_tag.get("data-lazy-src"))
            if src and src not in seen and _is_photo(src):
                seen.add(src)
                extra_imgs.append(src)
                if len(extra_imgs) >= 4:
                    break

        return updated_floor, (_json.dumps(extra_imgs) if extra_imgs else None)

    def scrape(self):
        """Scrape listings. Override in subclass."""
        raise NotImplementedError

    def parse_listing(self, element):
        """Parse a single listing element. Override in subclass."""
        raise NotImplementedError
