"""Database setup and models."""

import datetime
import json
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, Text, text
from sqlalchemy.orm import declarative_base, sessionmaker

from config import DATABASE_URL

# Railway (and Heroku) emit postgres:// but SQLAlchemy 2.x needs postgresql://
_db_url = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(_db_url, echo=False)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    external_id = Column(String, unique=True, nullable=False)  # site-specific ID
    source = Column(String, nullable=False)  # "imobiliare" or "storia"
    url = Column(String, nullable=False)
    title = Column(String)
    price = Column(Float)
    currency = Column(String, default="EUR")
    rooms = Column(Integer)
    surface = Column(Float)  # sqm
    year_built = Column(Integer)
    floor = Column(String)
    layout = Column(String)  # decomandat, semidecomandat, etc.
    neighborhood = Column(String)
    address = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    description = Column(Text)
    image_url = Column(String)
    extra_images = Column(String)  # JSON list of up to 4 extra photo URLs
    has_balcony = Column(Boolean)

    # Metadata
    first_seen = Column(DateTime, default=datetime.datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.datetime.utcnow)
    is_active = Column(Boolean, default=True)
    is_favorite = Column(Boolean, default=False)
    is_hidden = Column(Boolean, default=False)
    notes = Column(Text)

    def __repr__(self):
        return f"<Listing {self.source}:{self.external_id} - {self.title}>"

    def matches_area(self, target_area, target_neighborhoods):
        """Check if listing falls within the target area."""
        # Try coordinates first
        if self.latitude and self.longitude:
            return (
                target_area["lat_min"] <= self.latitude <= target_area["lat_max"]
                and target_area["lng_min"] <= self.longitude <= target_area["lng_max"]
            )
        # Fall back to neighborhood name matching
        if self.neighborhood:
            nb = self.neighborhood.lower().strip()
            return any(t in nb or nb in t for t in target_neighborhoods)
        return True  # If no location info, include it (user can filter manually)

    @property
    def extra_images_list(self):
        """Parse extra_images JSON string into a Python list (max 4 items)."""
        try:
            if not self.extra_images:
                return []
            return json.loads(self.extra_images)[:4]
        except Exception:
            return []

    @property
    def floor_display(self):
        """Return floor only when it contains a digit (e.g. '3/8', '3'); hides stale values like 'etajul'."""
        if self.floor and (any(c.isdigit() for c in self.floor) or self.floor == "parter"):
            return self.floor
        return None

    @property
    def price_display(self):
        if self.price:
            return f"{self.price:,.0f} {self.currency or 'EUR'}"
        return "N/A"

    @property
    def age_display(self):
        if not self.first_seen:
            return "unknown"
        delta = datetime.datetime.utcnow() - self.first_seen
        if delta.days == 0:
            hours = delta.seconds // 3600
            if hours == 0:
                return "just now"
            return f"{hours}h ago"
        if delta.days == 1:
            return "yesterday"
        return f"{delta.days}d ago"


def init_db():
    """Create all tables."""
    Base.metadata.create_all(engine)


def migrate_db():
    """Apply lightweight schema migrations (safe to re-run).

    Wraps every ALTER in a separate connection so that a failure on one
    statement does not abort the others, and the app still starts even if
    a migration cannot be applied (e.g. read-only replica, permission gap).
    """
    migrations = [
        "ALTER TABLE listings ADD COLUMN IF NOT EXISTS extra_images TEXT",
    ]
    for sql in migrations:
        try:
            with engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
        except Exception as exc:
            # Log and continue — a missing column is better than a dead process
            import logging as _log
            _log.getLogger(__name__).warning(
                f"migrate_db: could not apply '{sql}': {exc}"
            )


def get_db():
    """Get a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
