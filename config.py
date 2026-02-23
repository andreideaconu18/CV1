"""Configuration for the apartment rental scout."""

import os

# --- Search Criteria ---
SEARCH_CRITERIA = {
    "city": "bucuresti",
    "rooms": 2,
    "price_min": 550,
    "price_max": 650,
    "currency": "EUR",
    "layout": "decomandat",  # separate rooms, not open-plan
    "year_min": 1979,  # storia uses buildYearMin=year_min; imobiliare has no year URL filter
    "balcony": True,
}

# --- Target Area (bounding box) ---
# Southernmost: Eroii Revolutiei ~44.4137
# Northernmost: Aurel Vlaicu ~44.4530
# Westernmost: Parc Izvor ~26.0875
# Easternmost: Dristor ~26.1340
TARGET_AREA = {
    "lat_min": 44.4100,
    "lat_max": 44.4560,
    "lng_min": 26.0840,
    "lng_max": 26.1380,
}

# Neighborhoods that fall within the target area (fallback when no coords)
TARGET_NEIGHBORHOODS = [
    "unirii", "universitate", "romana", "piata romana",
    "victoriei", "piata victoriei", "izvor", "parc izvor",
    "eroii revolutiei", "eroilor", "dristor",
    "kogalniceanu", "cismigiu", "calea victoriei",
    "armeneasca", "mosilor", "stefan cel mare",
    "carol", "libertatii", "timpuri noi",
    "piata alba iulia", "alba iulia", "decebal",
    "muncii", "iancului", "obor",
    "mantuleasa", "batistei", "lahovari",
    "rosetti", "hristo botev", "traian",
    "centru", "centrul vechi", "old town",
    "calea calarasi", "calarasi", "nerva traian",
    "tineretului", "sincai",
]

# --- Scraping ---
SCRAPE_INTERVAL_MINUTES = int(os.environ.get("SCRAPE_INTERVAL", "15"))
REQUEST_TIMEOUT = 30
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

# --- Database ---
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///apartments.db")

# --- App ---
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")
PORT = int(os.environ.get("PORT", "8080"))
