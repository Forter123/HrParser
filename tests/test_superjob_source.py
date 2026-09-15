import pytest

from app.models import SearchQuery, SourceSeenEntry
from app.sources.superjob_source import SuperJobSource


def _search(db_session, keywords="python"):
    search = SearchQuery(title="Backend", keywords=keywords)
    db_session.add(search)
    db_session.commit()
    db_session.refresh(search)
    return search


def _configure(monkeypatch):
    monkeypatch.setattr("app.sources.superjob_source.settings.superjob_client_id", "app123")
    monkeypatch.setattr("app.sources.superjob_source.settings.superjob_client_secret", "secret")
    monkeypatch.setattr("app.sources.superjob_source.settings.superjob_login", "hr@company.com")
    monkeypatch.setattr("app.sources.superjob_source.settings.superjob_password", "pw")


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class FakeHttpClient:
    def __init__(self, token_response, resumes_responses):
        self._token_response = token_response
        self._resumes_responses = list(resumes_responses)
        self.get_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, data=None):
        return FakeResponse(self._token_response)

    async def get(self, url, headers=None, params=None):
        self.get_calls += 1
        return FakeResponse(self._resumes_responses.pop(0))


@pytest.mark.asyncio
async def test_returns_empty_when_not_configured(db_session):
    source = SuperJobSource()
    results = await source.fetch([_search(db_session)], db_session)
    assert results == []


@pytest.mark.asyncio
async def test_fetch_parses_resumes_into_raw_entries(db_session, monkeypatch):
    _configure(monkeypatch)
    search = _search(db_session, keywords="python")

    fake_client = FakeHttpClient(
        token_response={"access_token": "tok123", "expires_in": 3600},
        resumes_responses=[
            {
                "objects": [
                    {
                        "id": 555,
                        "profession": "Python developer",
                        "link": "https://superjob.ru/resume/555",
                        "clientInfo": {"firstname": "Ivan", "lastname": "Petrov"},
                        "dateChange": 1700000000,
                    }
                ]
            }
        ],
    )

    source = SuperJobSource()
    monkeypatch.setattr("app.sources.superjob_source.httpx.AsyncClient", lambda **kw: fake_client)

    results = await source.fetch([search], db_session)

    assert len(results) == 1
    matched_search, entry = results[0]
    assert matched_search.id == search.id
    assert entry.sender_id == "555"
    assert entry.sender_name == "Ivan Petrov"
    assert entry.text == "Python developer"
    assert entry.message_link == "https://superjob.ru/resume/555"
    assert entry.channel == "superjob"


@pytest.mark.asyncio
async def test_already_seen_resume_is_not_returned_again(db_session, monkeypatch):
    _configure(monkeypatch)
    search = _search(db_session, keywords="python")
    db_session.add(SourceSeenEntry(source="superjob", search_query_id=search.id, external_id="555"))
    db_session.commit()

    fake_client = FakeHttpClient(
        token_response={"access_token": "tok123", "expires_in": 3600},
        resumes_responses=[
            {
                "objects": [
                    {"id": 555, "profession": "Python developer", "link": "x", "clientInfo": {}},
                ]
            }
        ],
    )
    monkeypatch.setattr("app.sources.superjob_source.httpx.AsyncClient", lambda **kw: fake_client)

    source = SuperJobSource()
    results = await source.fetch([search], db_session)

    assert results == []


@pytest.mark.asyncio
async def test_search_without_keywords_is_skipped(db_session, monkeypatch):
    _configure(monkeypatch)
    search = SearchQuery(title="Empty", keywords="")
    db_session.add(search)
    db_session.commit()
    db_session.refresh(search)

    fake_client = FakeHttpClient(
        token_response={"access_token": "tok123", "expires_in": 3600},
        resumes_responses=[],
    )
    monkeypatch.setattr("app.sources.superjob_source.httpx.AsyncClient", lambda **kw: fake_client)

    source = SuperJobSource()
    results = await source.fetch([search], db_session)

    assert results == []
    assert fake_client.get_calls == 0
