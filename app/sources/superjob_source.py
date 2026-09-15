import logging
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import SearchQuery, SourceSeenEntry
from app.sources.base import RawEntry, Source

logger = logging.getLogger(__name__)

TOKEN_URL = "https://api.superjob.ru/2.0/oauth2/password/"
RESUMES_URL = "https://api.superjob.ru/2.0/resumes/"


class SuperJobSource(Source):
    """Collects candidate resumes from SuperJob via its official API.

    Requires an app registered at api.superjob.ru (client_id/client_secret)
    and an employer account (login/password) with resume-search access.
    Field names in the API response are matched on a best-effort basis from
    SuperJob's public docs — verify against a real response once credentials
    are available, and adjust `_to_raw_entry` if anything doesn't line up.
    """

    SOURCE_KEY = "superjob_api"

    def __init__(self) -> None:
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    def _is_configured(self) -> bool:
        return bool(
            settings.superjob_client_id
            and settings.superjob_client_secret
            and settings.superjob_login
            and settings.superjob_password
        )

    async def _get_token(self, client: httpx.AsyncClient) -> str | None:
        if self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token
        if not self._is_configured():
            logger.error("SuperJob credentials are not configured.")
            return None

        resp = await client.post(
            TOKEN_URL,
            data={
                "client_id": settings.superjob_client_id,
                "client_secret": settings.superjob_client_secret,
                "login": settings.superjob_login,
                "password": settings.superjob_password,
                "hostname": "superjob.ru",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expires_at = time.monotonic() + int(data.get("expires_in", 3600)) - 60
        return self._access_token

    async def fetch(self, searches: list[SearchQuery], db: Session) -> list[tuple[SearchQuery, RawEntry]]:
        if not self._is_configured():
            return []

        results: list[tuple[SearchQuery, RawEntry]] = []
        async with httpx.AsyncClient(timeout=15) as client:
            token = await self._get_token(client)
            if not token:
                return []

            headers = {
                "X-Api-App-Id": settings.superjob_client_id,
                "Authorization": f"Bearer {token}",
            }

            for search in searches:
                keywords = search.keyword_list()
                if not keywords:
                    continue
                try:
                    resumes = await self._search_resumes(client, headers, keywords)
                except httpx.HTTPError:
                    logger.exception("Failed to fetch SuperJob resumes for search %s", search.id)
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
        self, client: httpx.AsyncClient, headers: dict, keywords: list[str]
    ) -> list[dict]:
        resp = await client.get(
            RESUMES_URL,
            headers=headers,
            params={
                "keyword": " ".join(keywords),
                "count": 20,
                "order_field": "date_pub",
                "order_direction": "desc",
            },
        )
        resp.raise_for_status()
        return resp.json().get("objects", [])

    def _already_seen(self, db: Session, search_id: int, external_id: str) -> bool:
        existing = db.execute(
            select(SourceSeenEntry).where(
                SourceSeenEntry.source == "superjob",
                SourceSeenEntry.search_query_id == search_id,
                SourceSeenEntry.external_id == external_id,
            )
        ).scalar_one_or_none()
        return existing is not None

    def _mark_seen(self, db: Session, search_id: int, external_id: str) -> None:
        db.add(SourceSeenEntry(source="superjob", search_query_id=search_id, external_id=external_id))

    def _to_raw_entry(self, resume: dict, external_id: str) -> RawEntry:
        client_info = resume.get("clientInfo") or {}
        name = (
            " ".join(filter(None, [client_info.get("firstname"), client_info.get("lastname")]))
            or resume.get("profession")
            or "Без имени"
        )
        posted_ts = resume.get("dateChange") or resume.get("dateCreated") or resume.get("date_pub_last")
        posted_at = datetime.fromtimestamp(posted_ts, tz=timezone.utc) if posted_ts else datetime.now(timezone.utc)

        return RawEntry(
            source="superjob",
            sender_id=external_id,
            sender_name=name,
            text=resume.get("profession") or "",
            message_link=resume.get("link"),
            channel="superjob",
            posted_at=posted_at,
            external_message_id=external_id,
        )
