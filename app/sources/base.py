from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import SearchQuery


@dataclass
class RawEntry:
    sender_id: str | None
    sender_name: str | None
    text: str
    message_link: str | None
    channel: str
    posted_at: datetime
    external_message_id: str | None = None
    source: str = "telegram"


# Canonical registry of selectable sources, used both by the scheduler (to
# filter which searches a given Source instance gets called with) and by the
# /searches UI (to let users pick which sources run for a given search).
# Keyed separately from Candidate.source/RawEntry.source (which identifies
# where a candidate came from for display/dedup) — SOURCE_KEY identifies a
# *Source implementation*, since e.g. SuperJobSource and SuperJobScraperSource
# both attribute candidates to source="superjob" but are distinct, separately
# selectable Source classes.
SOURCE_CHOICES: list[tuple[str, str]] = [
    ("telegram", "Telegram"),
    ("superjob_api", "SuperJob (API)"),
    ("superjob_scraper", "SuperJob (скрапер)"),
    ("linkedin", "LinkedIn"),
    ("hh_api", "HH.ru (API)"),
    ("hh_scraper", "HH.ru (скрапер)"),
]
SOURCE_KEYS = {key for key, _ in SOURCE_CHOICES}


class Source(ABC):
    """Interface every candidate-collection source must implement.

    A source decides internally how to look things up (crawl shared channels,
    call a search API per query, etc.) — the only contract is: given the
    currently active searches, return the new raw entries found for each of
    them since the last poll, paired with the search they matched.
    """

    #: One of the keys in `SOURCE_CHOICES` above, identifying this
    #: implementation for the purposes of per-search source selection. Every
    #: concrete subclass must set this.
    SOURCE_KEY: str

    @abstractmethod
    async def fetch(self, searches: list[SearchQuery], db: Session) -> list[tuple[SearchQuery, RawEntry]]:
        """Return (search, entry) pairs for new candidate mentions found since
        the last poll, across all given active searches.

        Implementations are responsible for tracking their own read progress
        (e.g. persisting a last-seen id) using the given db session.
        """
        raise NotImplementedError
