import asyncio
import logging
from datetime import datetime, timezone

from linkedin_api import Linkedin
from linkedin_api.client import ChallengeException
from requests.exceptions import RequestException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import SearchQuery, SourceSeenEntry
from app.sources.base import RawEntry, Source

logger = logging.getLogger(__name__)


class LinkedInSource(Source):
    """Collects candidate profiles from LinkedIn people search.

    LinkedIn has no public API for third-party candidate search, so this uses
    the unofficial `linkedin-api` package, which authenticates with a regular
    LinkedIn account's email/password (like a logged-in browser session) and
    calls the same internal endpoints LinkedIn's own web UI uses. This is
    against LinkedIn's Terms of Service and carries a real risk of the
    account being rate-limited or restricted — only use an account you're
    prepared to lose, and keep poll frequency low.
    """

    SOURCE_KEY = "linkedin"

    def __init__(self) -> None:
        self._client: Linkedin | None = None

    def _is_configured(self) -> bool:
        return bool(settings.linkedin_email and settings.linkedin_password)

    def _get_client(self) -> Linkedin | None:
        if self._client is not None:
            return self._client
        if not self._is_configured():
            logger.error("LinkedIn credentials are not configured.")
            return None
        try:
            self._client = Linkedin(settings.linkedin_email, settings.linkedin_password)
        except ChallengeException:
            logger.exception("LinkedIn login requires a security challenge (2FA/captcha).")
            return None
        return self._client

    async def fetch(self, searches: list[SearchQuery], db: Session) -> list[tuple[SearchQuery, RawEntry]]:
        if not self._is_configured():
            return []

        results: list[tuple[SearchQuery, RawEntry]] = []
        for search in searches:
            keywords = search.keyword_list()
            if not keywords:
                continue
            try:
                profiles = await asyncio.to_thread(self._search_people, keywords)
            except (RequestException, ChallengeException):
                logger.exception("Failed to fetch LinkedIn profiles for search %s", search.id)
                continue

            for profile in profiles:
                external_id = str(profile.get("urn_id") or profile.get("public_id") or "")
                if not external_id or self._already_seen(db, search.id, external_id):
                    continue
                results.append((search, self._to_raw_entry(profile, external_id)))
                self._mark_seen(db, search.id, external_id)

        db.commit()
        return results

    def _search_people(self, keywords: list[str]) -> list[dict]:
        client = self._get_client()
        if not client:
            return []
        return client.search_people(keywords=" ".join(keywords), limit=20)

    def _already_seen(self, db: Session, search_id: int, external_id: str) -> bool:
        existing = db.execute(
            select(SourceSeenEntry).where(
                SourceSeenEntry.source == "linkedin",
                SourceSeenEntry.search_query_id == search_id,
                SourceSeenEntry.external_id == external_id,
            )
        ).scalar_one_or_none()
        return existing is not None

    def _mark_seen(self, db: Session, search_id: int, external_id: str) -> None:
        db.add(SourceSeenEntry(source="linkedin", search_query_id=search_id, external_id=external_id))

    def _to_raw_entry(self, profile: dict, external_id: str) -> RawEntry:
        name = profile.get("name") or " ".join(
            filter(None, [profile.get("first_name"), profile.get("last_name")])
        ) or "Без имени"
        headline = profile.get("jobtitle") or profile.get("headline") or ""
        location = profile.get("location") or ""
        text = " — ".join(filter(None, [headline, location]))
        public_id = profile.get("public_id")
        link = f"https://www.linkedin.com/in/{public_id}/" if public_id else None

        return RawEntry(
            source="linkedin",
            sender_id=external_id,
            sender_name=name,
            text=text,
            message_link=link,
            channel="linkedin",
            posted_at=datetime.now(timezone.utc),
            external_message_id=external_id,
        )
