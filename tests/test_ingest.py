from datetime import datetime, timezone

from app.models import Candidate, CandidateEntry, CandidateStatus, Comment, SearchQuery
from app.services.ingest import ingest_entry
from app.sources.base import RawEntry


def _entry(sender_id="1", text="Python developer"):
    return RawEntry(
        sender_id=sender_id,
        sender_name="Ivan",
        text=text,
        message_link="https://t.me/chan/1",
        channel="chan",
        posted_at=datetime.now(timezone.utc),
    )


def _search(db_session):
    search = SearchQuery(title="Backend", keywords="python")
    db_session.add(search)
    db_session.commit()
    db_session.refresh(search)
    return search


def test_ingest_new_entry_creates_candidate(db_session):
    search = _search(db_session)
    candidate, entry, is_new = ingest_entry(db_session, search, _entry())

    assert is_new is True
    assert entry.is_update is False
    assert candidate.external_sender_id == "1"

    stored_candidates = db_session.query(Candidate).all()
    assert len(stored_candidates) == 1


def test_ingest_duplicate_creates_update_entry_and_preserves_status_and_comments(db_session):
    search = _search(db_session)
    candidate, first_entry, _ = ingest_entry(db_session, search, _entry(sender_id="42", text="Python dev"))

    candidate.current_status = CandidateStatus.in_touch
    db_session.add(candidate)
    comment = Comment(candidate_id=candidate.id, user_id=1, text="Looks promising")
    db_session.add(comment)
    db_session.commit()

    candidate2, second_entry, is_new = ingest_entry(
        db_session, search, _entry(sender_id="42", text="Python dev, updated resume")
    )

    assert is_new is False
    assert candidate2.id == candidate.id
    assert second_entry.is_update is True

    db_session.refresh(candidate2)
    assert candidate2.current_status == CandidateStatus.in_touch

    entries = db_session.query(CandidateEntry).filter_by(candidate_id=candidate.id).all()
    assert len(entries) == 2

    comments = db_session.query(Comment).filter_by(candidate_id=candidate.id).all()
    assert len(comments) == 1
    assert comments[0].text == "Looks promising"

    assert db_session.query(Candidate).count() == 1
