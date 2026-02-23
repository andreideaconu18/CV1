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

    def scrape(self):
        """Scrape listings. Override in subclass."""
        raise NotImplementedError

    def parse_listing(self, element):
        """Parse a single listing element. Override in subclass."""
        raise NotImplementedError
