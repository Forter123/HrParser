import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import SearchQuery, SourceSeenEntry
from app.sources.base import RawEntry, Source

logger = logging.getLogger(__name__)

TOKEN_URL = "https://hh.ru/oauth/token"
RESUMES_URL = "https://api.hh.ru/resumes"

DEFAULT_RETRY_AFTER_SECONDS = 5.0
MAX_RATE_LIMIT_RETRIES = 3


class HHSource(Source):
    """Collects candidate resumes from hh.ru via its official employer API.

    Requires an app registered at dev.hh.ru (client_id/client_secret) and an
    initial access/refresh token pair obtained once through hh.ru's OAuth
    authorization_code flow, using an employer account with resume-database
    access. The access token is short-lived; this refreshes it automatically
    with the refresh token on a 401/403 and keeps the new pair in memory for
    the rest of the process's lifetime (persist it back to .env manually if
    the process restarts often, or the refresh token itself may need renewing
    from hh.ru's side eventually).

    Abuse-prevention measures (to reduce the risk of hh.ru rate-limiting or
    blocking the connected account — see `hh_request_delay_seconds` and
    `hh_max_searches_per_cycle` in `app/config.py`):
    - A short delay is inserted between requests for different searches
      within one poll cycle, instead of firing them all back-to-back.
    - Only the first `hh_max_searches_per_cycle` active searches are polled
      per cycle; the rest wait for the next cycle. This caps the worst-case
      burst when many searches are active at once.
    - A `429 Too Many Requests` response is treated as a signal to back off
      (honoring `Retry-After` when hh.ru sends one) and retried a bounded
      number of times, rather than immediately erroring out.
    The remaining lever is outside the code: keep search keywords specific
    (e.g. "senior python django" rather than just "python") — narrower
    searches mean fewer resumes fetched per cycle.
    """

    SOURCE_KEY = "hh_api"

    def __init__(self) -> None:
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    def _is_configured(self) -> bool:
        return bool(
            settings.hh_client_id
            and settings.hh_client_secret
            and settings.hh_access_token
            and settings.hh_refresh_token
        )

    def _headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "User-Agent": settings.hh_user_agent,
        }

    async def _refresh_access_token(self, client: httpx.AsyncClient) -> str | None:
        refresh_token = self._refresh_token or settings.hh_refresh_token
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": settings.hh_client_id,
                "client_secret": settings.hh_client_secret,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token", refresh_token)
        return self._access_token

    async def fetch(self, searches: list[SearchQuery], db: Session) -> list[tuple[SearchQuery, RawEntry]]:
        if not self._is_configured():
            return []

        searches_to_poll = searches[: settings.hh_max_searches_per_cycle]
        if len(searches) > len(searches_to_poll):
            logger.warning(
                "hh.ru: %d active searches, only polling the first %d this cycle "
                "(hh_max_searches_per_cycle) to avoid bursting the API",
                len(searches),
                len(searches_to_poll),
            )

        results: list[tuple[SearchQuery, RawEntry]] = []
        token = self._access_token or settings.hh_access_token

        async with httpx.AsyncClient(timeout=15) as client:
            for i, search in enumerate(searches_to_poll):
                keywords = search.keyword_list()
                if not keywords:
                    continue

                if i > 0 and settings.hh_request_delay_seconds > 0:
                    await asyncio.sleep(settings.hh_request_delay_seconds)

                try:
                    resumes, token = await self._search_resumes(client, token, keywords)
                except httpx.HTTPError:
                    logger.exception("Failed to fetch hh.ru resumes for search %s", search.id)
                    continue

                for resume in resumes:
                    external_id = str(resume.get("id") or "")
                    if not external_id or self._already_seen(db, search.id, external_id):
                        continue
                    results.append((search, self._to_raw_entry(resume, external_id)))
                    self._mark_seen(db, search.id, external_id)

            db.commit()
        return results

    async def _search_resumes(
        self, client: httpx.AsyncClient, token: str, keywords: list[str]
    ) -> tuple[list[dict], str]:
        params = {"text": " ".join(keywords), "per_page": 20, "order_by": "publication_time"}

        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            resp = await client.get(RESUMES_URL, headers=self._headers(token), params=params)

            if resp.status_code in (401, 403):
                token = await self._refresh_access_token(client)
                resp = await client.get(RESUMES_URL, headers=self._headers(token), params=params)

            if resp.status_code == 429:
                if attempt == MAX_RATE_LIMIT_RETRIES:
                    resp.raise_for_status()
                wait_seconds = self._parse_retry_after(resp.headers.get("Retry-After"))
                logger.warning(
                    "hh.ru rate limit hit (429), backing off %.1fs (attempt %d/%d)",
                    wait_seconds,
                    attempt + 1,
                    MAX_RATE_LIMIT_RETRIES,
                )
                await asyncio.sleep(wait_seconds)
                continue

            resp.raise_for_status()
            return resp.json().get("items", []), token

        return [], token

    def _parse_retry_after(self, value: str | None) -> float:
        if value:
            try:
                return float(value)
            except ValueError:
                pass
        return DEFAULT_RETRY_AFTER_SECONDS

    def _already_seen(self, db: Session, search_id: int, external_id: str) -> bool:
        existing = db.execute(
            select(SourceSeenEntry).where(
                SourceSeenEntry.source == "hh",
                SourceSeenEntry.search_query_id == search_id,
                SourceSeenEntry.external_id == external_id,
            )
        ).scalar_one_or_none()
        return existing is not None

    def _mark_seen(self, db: Session, search_id: int, external_id: str) -> None:
        db.add(SourceSeenEntry(source="hh", search_query_id=search_id, external_id=external_id))

    def _to_raw_entry(self, resume: dict, external_id: str) -> RawEntry:
        name = (
            " ".join(filter(None, [resume.get("first_name"), resume.get("last_name")]))
            or resume.get("title")
            or "Без имени"
        )
        updated_at = resume.get("updated_at") or resume.get("txt_lst_upd") or resume.get("published_at")
        posted_at = self._parse_datetime(updated_at)

        return RawEntry(
            source="hh",
            sender_id=external_id,
            sender_name=name,
            text=resume.get("title") or "",
            message_link=resume.get("alternate_url"),
            channel="hh",
            posted_at=posted_at,
            external_message_id=external_id,
        )

    def _parse_datetime(self, value: str | None) -> datetime:
        if value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
        return datetime.now(timezone.utc)
