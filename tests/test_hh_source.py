from unittest.mock import AsyncMock

import pytest

from app.models import SearchQuery, SourceSeenEntry
from app.sources.hh_source import HHSource


def _search(db_session, keywords="python"):
    search = SearchQuery(title="Backend", keywords=keywords)
    db_session.add(search)
    db_session.commit()
    db_session.refresh(search)
    return search


def _configure(monkeypatch):
    monkeypatch.setattr("app.sources.hh_source.settings.hh_client_id", "app123")
    monkeypatch.setattr("app.sources.hh_source.settings.hh_client_secret", "secret")
    monkeypatch.setattr("app.sources.hh_source.settings.hh_access_token", "tok123")
    monkeypatch.setattr("app.sources.hh_source.settings.hh_refresh_token", "refresh123")
    # Keep tests fast: no artificial delay between requests unless a test opts in.
    monkeypatch.setattr("app.sources.hh_source.settings.hh_request_delay_seconds", 0)


class FakeResponse:
    def __init__(self, json_data, status_code=200, headers=None):
        self._json = json_data
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class FakeHttpClient:
    def __init__(self, resumes_responses, token_response=None):
        self._resumes_responses = list(resumes_responses)
        self._token_response = token_response
        self.get_calls = 0
        self.post_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None, params=None):
        self.get_calls += 1
        return FakeResponse(self._resumes_responses.pop(0))

    async def post(self, url, data=None):
        self.post_calls += 1
        return FakeResponse(self._token_response)


@pytest.mark.asyncio
async def test_returns_empty_when_not_configured(db_session):
    source = HHSource()
    results = await source.fetch([_search(db_session)], db_session)
    assert results == []


@pytest.mark.asyncio
async def test_fetch_parses_resumes_into_raw_entries(db_session, monkeypatch):
    _configure(monkeypatch)
    search = _search(db_session, keywords="python")

    fake_client = FakeHttpClient(
        resumes_responses=[
            {
                "items": [
                    {
                        "id": "555",
                        "title": "Python developer",
                        "alternate_url": "https://hh.ru/resume/555",
                        "first_name": "Ivan",
                        "last_name": "Petrov",
                        "updated_at": "2024-01-01T12:00:00+0300",
                    }
                ]
            }
        ],
    )

    source = HHSource()
    monkeypatch.setattr("app.sources.hh_source.httpx.AsyncClient", lambda **kw: fake_client)

    results = await source.fetch([search], db_session)

    assert len(results) == 1
    matched_search, entry = results[0]
    assert matched_search.id == search.id
    assert entry.source == "hh"
    assert entry.sender_id == "555"
    assert entry.sender_name == "Ivan Petrov"
    assert entry.text == "Python developer"
    assert entry.message_link == "https://hh.ru/resume/555"
    assert entry.channel == "hh"


@pytest.mark.asyncio
async def test_already_seen_resume_is_not_returned_again(db_session, monkeypatch):
    _configure(monkeypatch)
    search = _search(db_session, keywords="python")
    db_session.add(SourceSeenEntry(source="hh", search_query_id=search.id, external_id="555"))
    db_session.commit()

    fake_client = FakeHttpClient(
        resumes_responses=[
            {"items": [{"id": "555", "title": "Python developer", "alternate_url": "x"}]}
        ],
    )
    monkeypatch.setattr("app.sources.hh_source.httpx.AsyncClient", lambda **kw: fake_client)

    source = HHSource()
    results = await source.fetch([search], db_session)

    assert results == []


@pytest.mark.asyncio
async def test_search_without_keywords_is_skipped(db_session, monkeypatch):
    _configure(monkeypatch)
    search = SearchQuery(title="Empty", keywords="")
    db_session.add(search)
    db_session.commit()
    db_session.refresh(search)

    fake_client = FakeHttpClient(resumes_responses=[])
    monkeypatch.setattr("app.sources.hh_source.httpx.AsyncClient", lambda **kw: fake_client)

    source = HHSource()
    results = await source.fetch([search], db_session)

    assert results == []
    assert fake_client.get_calls == 0


@pytest.mark.asyncio
async def test_expired_token_triggers_refresh_and_retry(db_session, monkeypatch):
    _configure(monkeypatch)
    search = _search(db_session, keywords="python")

    fake_client = FakeHttpClient(
        resumes_responses=[
            {"items": []},  # first attempt: 401
            {"items": [{"id": "1", "title": "Dev", "alternate_url": "x"}]},  # retry after refresh
        ],
        token_response={"access_token": "newtok", "refresh_token": "newrefresh"},
    )

    async def get_with_401_then_ok(url, headers=None, params=None):
        fake_client.get_calls += 1
        if fake_client.get_calls == 1:
            return FakeResponse({}, status_code=401)
        return FakeResponse(fake_client._resumes_responses.pop())

    fake_client.get = get_with_401_then_ok
    monkeypatch.setattr("app.sources.hh_source.httpx.AsyncClient", lambda **kw: fake_client)

    source = HHSource()
    results = await source.fetch([search], db_session)

    assert fake_client.post_calls == 1
    assert len(results) == 1
    assert results[0][1].sender_id == "1"


@pytest.mark.asyncio
async def test_backs_off_and_retries_on_429(db_session, monkeypatch):
    _configure(monkeypatch)
    search = _search(db_session, keywords="python")

    responses = [
        FakeResponse({}, status_code=429, headers={"Retry-After": "3"}),
        FakeResponse({"items": [{"id": "1", "title": "Dev", "alternate_url": "x"}]}),
    ]

    async def get(url, headers=None, params=None):
        fake_client.get_calls += 1
        return responses.pop(0)

    fake_client = FakeHttpClient(resumes_responses=[])
    fake_client.get = get
    monkeypatch.setattr("app.sources.hh_source.httpx.AsyncClient", lambda **kw: fake_client)

    sleep_mock = AsyncMock()
    monkeypatch.setattr("app.sources.hh_source.asyncio.sleep", sleep_mock)

    source = HHSource()
    results = await source.fetch([search], db_session)

    assert len(results) == 1
    sleep_mock.assert_awaited_once_with(3.0)


@pytest.mark.asyncio
async def test_gives_up_after_max_rate_limit_retries(db_session, monkeypatch):
    _configure(monkeypatch)
    search = _search(db_session, keywords="python")

    async def always_429(url, headers=None, params=None):
        fake_client.get_calls += 1
        return FakeResponse({"items": []}, status_code=429)

    fake_client = FakeHttpClient(resumes_responses=[])
    fake_client.get = always_429
    monkeypatch.setattr("app.sources.hh_source.httpx.AsyncClient", lambda **kw: fake_client)
    monkeypatch.setattr("app.sources.hh_source.asyncio.sleep", AsyncMock())

    source = HHSource()
    results = await source.fetch([search], db_session)

    assert results == []
    # initial attempt + MAX_RATE_LIMIT_RETRIES retries, no more
    from app.sources.hh_source import MAX_RATE_LIMIT_RETRIES

    assert fake_client.get_calls == MAX_RATE_LIMIT_RETRIES + 1


@pytest.mark.asyncio
async def test_delay_inserted_between_multiple_searches(db_session, monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr("app.sources.hh_source.settings.hh_request_delay_seconds", 2.0)
    search1 = _search(db_session, keywords="python")
    search2 = _search(db_session, keywords="java")

    fake_client = FakeHttpClient(
        resumes_responses=[{"items": []}, {"items": []}],
    )
    monkeypatch.setattr("app.sources.hh_source.httpx.AsyncClient", lambda **kw: fake_client)
    sleep_mock = AsyncMock()
    monkeypatch.setattr("app.sources.hh_source.asyncio.sleep", sleep_mock)

    source = HHSource()
    await source.fetch([search1, search2], db_session)

    sleep_mock.assert_awaited_once_with(2.0)


@pytest.mark.asyncio
async def test_max_searches_per_cycle_limits_how_many_are_polled(db_session, monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr("app.sources.hh_source.settings.hh_max_searches_per_cycle", 2)
    searches = [_search(db_session, keywords=f"kw{i}") for i in range(4)]

    fake_client = FakeHttpClient(resumes_responses=[{"items": []}, {"items": []}])
    monkeypatch.setattr("app.sources.hh_source.httpx.AsyncClient", lambda **kw: fake_client)

    source = HHSource()
    await source.fetch(searches, db_session)

    assert fake_client.get_calls == 2
