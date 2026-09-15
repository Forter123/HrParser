from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Candidate
from app.sources.base import RawEntry


def find_duplicate(db: Session, entry: RawEntry) -> Candidate | None:
    """Find an existing candidate matching this raw entry.

    Match by same sender id first; fall back to fuzzy text similarity against
    each candidate's latest message. Only ever compares within the same source,
    since sender ids and message text are not comparable across sources.
    """
    if entry.sender_id:
        existing = db.execute(
            select(Candidate).where(
                Candidate.source == entry.source,
                Candidate.external_sender_id == entry.sender_id,
            )
        ).scalar_one_or_none()
        if existing:
            return existing

    threshold = settings.dedup_similarity_threshold
    candidates = db.execute(select(Candidate).where(Candidate.source == entry.source)).scalars().all()
    for candidate in candidates:
        latest = candidate.latest_entry()
        if not latest:
            continue
        score = fuzz.token_set_ratio(entry.text, latest.message_text)
        if score >= threshold:
            return candidate

    return None
