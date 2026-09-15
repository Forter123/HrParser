from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.models import Candidate, SearchQuery, SearchStatus
from app.sources.base import RawEntry
from app.worker import scheduler as scheduler_module


class FakeSource:
    def __init__(self, matches=None, raise_exc=False, source_key="fake"):
        self._matches = matches or []
        self._raise = raise_exc
        self.called = False
        self.called_with_searches = None
        self.SOURCE_KEY = source_key

    async def fetch(self, searches, db):
        self.called = True
        self.called_with_searches = searches
        if self._raise:
            raise RuntimeError("boom")
        return self._matches


def _entry(text="Python dev", sender_id="1"):
    return RawEntry(
        source="telegram",
        sender_id=sender_id,
        sender_name="Ivan",
        text=text,
        message_link="https://t.me/c/1",
        channel="c",
        posted_at=datetime.now(timezone.utc),
    )


def _active_search(SessionTest, keywords="python"):
    session = SessionTest()
    search = SearchQuery(title="Backend", keywords=keywords, status=SearchStatus.active)
    session.add(search)
    session.commit()
    session.refresh(search)
    session.close()
    return search


@pytest.mark.asyncio
async def test_poll_once_skips_sources_when_no_active_searches(monkeypatch, SessionTest):
    monkeypatch.setattr(scheduler_module, "SessionLocal", SessionTest)
    fake = FakeSource()
    monkeypatch.setattr(scheduler_module, "_sources", [fake])

    await scheduler_module.poll_once()

    assert fake.called is False


@pytest.mark.asyncio
async def test_poll_once_ingests_matches_and_broadcasts(monkeypatch, SessionTest):
    monkeypatch.setattr(scheduler_module, "SessionLocal", SessionTest)
    search = _active_search(SessionTest)

    fake = FakeSource(matches=[(search, _entry())])
    monkeypatch.setattr(scheduler_module, "_sources", [fake])

    broadcast_mock = AsyncMock()
    monkeypatch.setattr(scheduler_module.manager, "broadcast", broadcast_mock)

    await scheduler_module.poll_once()

    session = SessionTest()
    candidates = session.query(Candidate).all()
    session.close()

    assert len(candidates) == 1
    assert candidates[0].source == "telegram"
    broadcast_mock.assert_awaited_once_with("candidate_new", {"candidate_id": candidates[0].id})


@pytest.mark.asyncio
async def test_poll_once_continues_when_one_source_raises(monkeypatch, SessionTest):
    monkeypatch.setattr(scheduler_module, "SessionLocal", SessionTest)
    search = _active_search(SessionTest)

    failing = FakeSource(raise_exc=True)
    working = FakeSource(matches=[(search, _entry(sender_id="2"))])
    monkeypatch.setattr(scheduler_module, "_sources", [failing, working])
    monkeypatch.setattr(scheduler_module.manager, "broadcast", AsyncMock())

    await scheduler_module.poll_once()

    assert failing.called is True
    assert working.called is True

    session = SessionTest()
    candidates = session.query(Candidate).all()
    session.close()
    assert len(candidates) == 1


@pytest.mark.asyncio
async def test_poll_once_only_calls_source_for_searches_that_select_it(monkeypatch, SessionTest):
    monkeypatch.setattr(scheduler_module, "SessionLocal", SessionTest)

    session = SessionTest()
    all_sources_search = SearchQuery(title="Any", keywords="python", status=SearchStatus.active)
    telegram_only_search = SearchQuery(
        title="Telegram only", keywords="java", status=SearchStatus.active, sources="telegram"
    )
    hh_only_search = SearchQuery(
        title="HH only", keywords="go", status=SearchStatus.active, sources="hh_api"
    )
    session.add_all([all_sources_search, telegram_only_search, hh_only_search])
    session.commit()
    for s in (all_sources_search, telegram_only_search, hh_only_search):
        session.refresh(s)
    session.close()

    telegram_source = FakeSource(source_key="telegram")
    hh_source = FakeSource(source_key="hh_api")
    monkeypatch.setattr(scheduler_module, "_sources", [telegram_source, hh_source])

    await scheduler_module.poll_once()

    telegram_titles = {s.title for s in telegram_source.called_with_searches}
    hh_titles = {s.title for s in hh_source.called_with_searches}

    assert telegram_titles == {"Any", "Telegram only"}
    assert hh_titles == {"Any", "HH only"}


@pytest.mark.asyncio
async def test_poll_once_skips_source_entirely_when_no_search_selects_it(monkeypatch, SessionTest):
    monkeypatch.setattr(scheduler_module, "SessionLocal", SessionTest)
    _active_search(SessionTest, keywords="python")  # runs on all sources (no sources set)

    session = SessionTest()
    linkedin_only_search = SearchQuery(
        title="LinkedIn only", keywords="java", status=SearchStatus.active, sources="linkedin"
    )
    session.add(linkedin_only_search)
    session.commit()
    session.close()

    hh_source = FakeSource(source_key="hh_api")
    monkeypatch.setattr(scheduler_module, "_sources", [hh_source])

    await scheduler_module.poll_once()

    # The "all sources" search still runs on hh_api, so it's NOT fully skipped.
    assert hh_source.called is True
    titles = {s.title for s in hh_source.called_with_searches}
    assert titles == {"Backend"}
    assert "LinkedIn only" not in titles
