from datetime import datetime, timezone

from app.models import Candidate, CandidateEntry
from app.services.dedup import find_duplicate
from app.sources.base import RawEntry


def _entry(sender_id="123", text="Python developer, 5 years experience"):
    return RawEntry(
        sender_id=sender_id,
        sender_name="Ivan",
        text=text,
        message_link="https://t.me/chan/1",
        channel="chan",
        posted_at=datetime.now(timezone.utc),
    )


def _seed_candidate(db_session, sender_id="123", text="Python developer, 5 years experience"):
    candidate = Candidate(source="telegram", external_sender_id=sender_id, sender_name="Ivan")
    db_session.add(candidate)
    db_session.flush()
    entry = CandidateEntry(candidate_id=candidate.id, message_text=text, is_update=False)
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def test_dedup_matches_same_sender_id(db_session):
    existing = _seed_candidate(db_session, sender_id="123", text="Anything at all here")
    result = find_duplicate(db_session, _entry(sender_id="123", text="totally different text"))
    assert result is not None
    assert result.id == existing.id


def test_dedup_matches_fuzzy_similar_text(db_session):
    existing = _seed_candidate(db_session, sender_id="999", text="Python developer, 5 years experience, Django")
    # different sender, near-identical text
    result = find_duplicate(
        db_session, _entry(sender_id="888", text="Python developer 5 years experience Django")
    )
    assert result is not None
    assert result.id == existing.id


def test_dedup_no_match_for_unrelated_text(db_session):
    _seed_candidate(db_session, sender_id="999", text="Python developer, 5 years experience")
    result = find_duplicate(
        db_session, _entry(sender_id="777", text="Looking for a marketing manager role in retail")
    )
    assert result is None
