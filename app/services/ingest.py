from sqlalchemy.orm import Session

from app.models import Candidate, CandidateEntry, SearchQuery
from app.services.dedup import find_duplicate
from app.sources.base import RawEntry


def ingest_entry(db: Session, search: SearchQuery, entry: RawEntry) -> tuple[Candidate, CandidateEntry, bool]:
    """Persist a raw entry as a new candidate or an update to an existing one.

    Returns (candidate, candidate_entry, is_new_candidate).
    """
    existing = find_duplicate(db, entry)

    if existing is None:
        candidate = Candidate(
            source=entry.source,
            external_sender_id=entry.sender_id,
            sender_name=entry.sender_name,
        )
        db.add(candidate)
        db.flush()
        is_new = True
    else:
        candidate = existing
        is_new = False

    candidate_entry = CandidateEntry(
        candidate_id=candidate.id,
        search_query_id=search.id,
        message_text=entry.text,
        message_link=entry.message_link,
        source_channel=entry.channel,
        is_update=not is_new,
    )
    db.add(candidate_entry)
    db.commit()
    db.refresh(candidate)
    db.refresh(candidate_entry)
    return candidate, candidate_entry, is_new
