import pytest

from app.models import SearchQuery, SourceSeenEntry
from app.sources.linkedin_source import LinkedInSource


def _search(db_session, keywords="python"):
    search = SearchQuery(title="Backend", keywords=keywords)
    db_session.add(search)
    db_session.commit()
    db_session.refresh(search)
    return search


def _configure(monkeypatch):
    monkeypatch.setattr("app.sources.linkedin_source.settings.linkedin_email", "hr@company.com")
    monkeypatch.setattr("app.sources.linkedin_source.settings.linkedin_password", "pw")


class FakeLinkedin:
    def __init__(self, profiles):
        self._profiles = profiles
        self.search_calls = []

    def search_people(self, keywords=None, limit=None):
        self.search_calls.append(keywords)
        return self._profiles


@pytest.mark.asyncio
async def test_returns_empty_when_not_configured(db_session):
    source = LinkedInSource()
    results = await source.fetch([_search(db_session)], db_session)
    assert results == []


@pytest.mark.asyncio
async def test_fetch_parses_profiles_into_raw_entries(db_session, monkeypatch):
    _configure(monkeypatch)
    search = _search(db_session, keywords="python")

    fake_client = FakeLinkedin(
        [
            {
                "urn_id": "abc123",
                "public_id": "ivan-petrov",
                "name": "Ivan Petrov",
                "jobtitle": "Python developer",
                "location": "Moscow",
            }
        ]
    )

    source = LinkedInSource()
    monkeypatch.setattr(source, "_get_client", lambda: fake_client)

    results = await source.fetch([search], db_session)

    assert len(results) == 1
    matched_search, entry = results[0]
    assert matched_search.id == search.id
    assert entry.source == "linkedin"
    assert entry.sender_id == "abc123"
    assert entry.sender_name == "Ivan Petrov"
    assert entry.text == "Python developer — Moscow"
    assert entry.message_link == "https://www.linkedin.com/in/ivan-petrov/"
    assert entry.channel == "linkedin"
    assert fake_client.search_calls == ["python"]


@pytest.mark.asyncio
async def test_already_seen_profile_is_not_returned_again(db_session, monkeypatch):
    _configure(monkeypatch)
    search = _search(db_session, keywords="python")
    db_session.add(SourceSeenEntry(source="linkedin", search_query_id=search.id, external_id="abc123"))
    db_session.commit()

    fake_client = FakeLinkedin([{"urn_id": "abc123", "public_id": "ivan-petrov", "name": "Ivan Petrov"}])

    source = LinkedInSource()
    monkeypatch.setattr(source, "_get_client", lambda: fake_client)

    results = await source.fetch([search], db_session)

    assert results == []


@pytest.mark.asyncio
async def test_search_without_keywords_is_skipped(db_session, monkeypatch):
    _configure(monkeypatch)
    search = SearchQuery(title="Empty", keywords="")
    db_session.add(search)
    db_session.commit()
    db_session.refresh(search)

    fake_client = FakeLinkedin([])
    source = LinkedInSource()
    monkeypatch.setattr(source, "_get_client", lambda: fake_client)

    results = await source.fetch([search], db_session)

    assert results == []
    assert fake_client.search_calls == []
