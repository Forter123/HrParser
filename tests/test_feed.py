from datetime import datetime, timedelta, timezone

from app.models import Candidate, CandidateEntry, CandidateStatus, Comment
from app.routers.feed import _card_context


def _seed_candidate(db_session, text="Python developer", source="telegram", sender_id="1", status=None):
    candidate = Candidate(source=source, external_sender_id=sender_id, sender_name="Ivan")
    if status is not None:
        candidate.current_status = status
    db_session.add(candidate)
    db_session.flush()
    entry = CandidateEntry(candidate_id=candidate.id, message_text=text, message_link="https://t.me/c/1")
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def test_feed_shows_candidate(logged_in_client, db_session):
    _seed_candidate(db_session, text="Python developer, 3 years")
    client, _ = logged_in_client
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Python developer, 3 years" in resp.text


def test_status_change_persists_and_is_returned(logged_in_client, db_session):
    candidate = _seed_candidate(db_session)
    client, _ = logged_in_client

    resp = client.post(
        f"/candidates/{candidate.id}/status", data={"status": "на связи"}, follow_redirects=False
    )
    assert resp.status_code == 303

    db_session.expire_all()
    updated = db_session.get(Candidate, candidate.id)
    assert updated.current_status == CandidateStatus.in_touch


def test_add_comment_appears_under_candidate(logged_in_client, db_session):
    candidate = _seed_candidate(db_session)
    client, _ = logged_in_client

    resp = client.post(f"/candidates/{candidate.id}/comments", data={"text": "Great fit"}, follow_redirects=False)
    assert resp.status_code == 303

    comments = db_session.query(Comment).filter_by(candidate_id=candidate.id).all()
    assert len(comments) == 1
    assert comments[0].text == "Great fit"

    feed_resp = client.get("/")
    assert "Great fit" in feed_resp.text


def test_delete_candidate_cascades_entries_and_comments(logged_in_client, db_session):
    candidate = _seed_candidate(db_session)
    db_session.add(Comment(candidate_id=candidate.id, user_id=1, text="note"))
    db_session.commit()
    candidate_id = candidate.id

    client, _ = logged_in_client
    resp = client.post(f"/candidates/{candidate_id}/delete", follow_redirects=False)
    assert resp.status_code == 303

    db_session.expire_all()
    assert db_session.get(Candidate, candidate_id) is None
    assert db_session.query(CandidateEntry).filter_by(candidate_id=candidate_id).count() == 0
    assert db_session.query(Comment).filter_by(candidate_id=candidate_id).count() == 0


def test_badge_new_when_entry_after_last_seen(db_session):
    candidate = _seed_candidate(db_session)
    last_seen = datetime.now(timezone.utc) - timedelta(hours=1)
    ctx = _card_context(db_session, candidate, last_seen)
    assert ctx["badge"] == "Новая"


def test_badge_update_when_entry_is_update_and_after_last_seen(db_session):
    candidate = _seed_candidate(db_session)
    entry2 = CandidateEntry(candidate_id=candidate.id, message_text="Updated resume", is_update=True)
    db_session.add(entry2)
    db_session.commit()
    last_seen = datetime.now(timezone.utc) - timedelta(hours=1)
    ctx = _card_context(db_session, candidate, last_seen)
    assert ctx["badge"] == "Обновлено"


def test_badge_none_when_seen_after_entry(db_session):
    candidate = _seed_candidate(db_session)
    last_seen = datetime.now(timezone.utc) + timedelta(hours=1)
    ctx = _card_context(db_session, candidate, last_seen)
    assert ctx["badge"] is None


def test_filter_by_source_only_shows_matching_candidates(logged_in_client, db_session):
    _seed_candidate(db_session, text="Python from Telegram", source="telegram", sender_id="1")
    _seed_candidate(db_session, text="Python from SuperJob", source="superjob", sender_id="2")
    client, _ = logged_in_client

    resp = client.get("/?source=superjob")

    assert resp.status_code == 200
    assert "Python from SuperJob" in resp.text
    assert "Python from Telegram" not in resp.text


def test_filter_by_status_only_shows_matching_candidates(logged_in_client, db_session):
    _seed_candidate(db_session, text="Interesting one", sender_id="1", status=CandidateStatus.interesting)
    _seed_candidate(db_session, text="Not a fit", sender_id="2", status=CandidateStatus.not_fit)
    client, _ = logged_in_client

    resp = client.get(f"/?status={CandidateStatus.not_fit.value}")

    assert resp.status_code == 200
    assert "Not a fit" in resp.text
    assert "Interesting one" not in resp.text


def test_filter_by_source_and_status_combined(logged_in_client, db_session):
    _seed_candidate(
        db_session, text="Match", source="hh", sender_id="1", status=CandidateStatus.in_touch
    )
    _seed_candidate(
        db_session, text="Wrong status", source="hh", sender_id="2", status=CandidateStatus.interesting
    )
    _seed_candidate(
        db_session, text="Wrong source", source="telegram", sender_id="3", status=CandidateStatus.in_touch
    )
    client, _ = logged_in_client

    resp = client.get(f"/?source=hh&status={CandidateStatus.in_touch.value}")

    assert resp.status_code == 200
    assert "Match" in resp.text
    assert "Wrong status" not in resp.text
    assert "Wrong source" not in resp.text


def test_no_filters_shows_all_candidates(logged_in_client, db_session):
    _seed_candidate(db_session, text="From Telegram", source="telegram", sender_id="1")
    _seed_candidate(db_session, text="From LinkedIn", source="linkedin", sender_id="2")
    client, _ = logged_in_client

    resp = client.get("/")

    assert "From Telegram" in resp.text
    assert "From LinkedIn" in resp.text


def test_card_context_includes_source_label():
    from app.routers.feed import SOURCE_LABELS

    assert SOURCE_LABELS["telegram"] == "Telegram"
    assert SOURCE_LABELS["superjob"] == "SuperJob"
    assert SOURCE_LABELS["linkedin"] == "LinkedIn"
    assert SOURCE_LABELS["hh"] == "HH.ru"
