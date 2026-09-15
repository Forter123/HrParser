import asyncio
import logging

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import SearchQuery, SearchStatus
from app.realtime import manager
from app.services.ingest import ingest_entry
from app.sources.hh_scraper_source import HHScraperSource
from app.sources.hh_source import HHSource
from app.sources.linkedin_source import LinkedInSource
from app.sources.superjob_scraper_source import SuperJobScraperSource
from app.sources.superjob_source import SuperJobSource
from app.sources.telegram_source import TelegramSource

logger = logging.getLogger(__name__)

# Each site has an official/paid source and a free Vision-browser-automation
# fallback (see their docstrings for ToS/152-FZ risk) — both no-op when not
# configured, so it's safe to list both per site.
_sources = [
    TelegramSource(),
    SuperJobSource(),
    SuperJobScraperSource(),
    LinkedInSource(),
    HHSource(),
    HHScraperSource(),
]


async def poll_once() -> None:
    db = SessionLocal()
    try:
        searches = (
            db.execute(select(SearchQuery).where(SearchQuery.status == SearchStatus.active))
            .scalars()
            .all()
        )
        if not searches:
            return

        for source in _sources:
            relevant_searches = [s for s in searches if s.runs_on_source(source.SOURCE_KEY)]
            if not relevant_searches:
                continue

            try:
                matches = await source.fetch(relevant_searches, db)
            except Exception:
                logger.exception("Failed to fetch entries from %s", type(source).__name__)
                continue

            for search, entry in matches:
                candidate, candidate_entry, is_new = ingest_entry(db, search, entry)
                await manager.broadcast(
                    "candidate_new" if is_new else "candidate_updated",
                    {"candidate_id": candidate.id},
                )
    finally:
        db.close()


async def run_forever() -> None:
    while True:
        try:
            await poll_once()
        except Exception:
            logger.exception("Polling cycle failed")
        await asyncio.sleep(settings.poll_interval_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())
