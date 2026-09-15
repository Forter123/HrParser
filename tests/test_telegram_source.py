from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.models import SearchQuery, TelegramChannel
from app.sources.telegram_source import TelegramSource


class FakeSender:
    def __init__(self, id, first_name=None, last_name=None, username=None):
        self.id = id
        self.first_name = first_name
        self.last_name = last_name
        self.username = username


class FakeMessage:
    def __init__(self, id, text, sender):
        self.id = id
        self.message = text
        self.date = datetime.now(timezone.utc)
        self._sender = sender

    async def get_sender(self):
        return self._sender


class FakeClient:
    def __init__(self, messages):
        self._messages = messages
        self.connected = False

    def is_connected(self):
        return self.connected

    async def connect(self):
        self.connected = True

    async def is_user_authorized(self):
        return True

    def iter_messages(self, username, min_id=0, limit=200):
        async def gen():
            for m in self._messages:
                if m.id > min_id:
                    yield m

        return gen()


def _channel(db_session, last_message_id=None):
    channel = TelegramChannel(username="jobs_channel", last_message_id=last_message_id)
    db_session.add(channel)
    db_session.commit()
    db_session.refresh(channel)
    return channel


def _search(db_session, keywords="python"):
    search = SearchQuery(title="Backend", keywords=keywords)
    db_session.add(search)
    db_session.commit()
    db_session.refresh(search)
    return search


@pytest.mark.asyncio
async def test_fetch_matches_entries_against_search_keywords(db_session):
    """Channels are shared across searches; the source fetches everything new
    and matches it per search against that search's own keywords."""
    _channel(db_session)
    search = _search(db_session, keywords="python")
    messages = [
        FakeMessage(1, "Looking for a PYTHON developer", FakeSender(10, "Ivan")),
        FakeMessage(2, "Looking for a marketing manager", FakeSender(11, "Petr")),
    ]
    fake_client = FakeClient(messages)

    source = TelegramSource()
    with patch("app.sources.telegram_source.TelegramClient", return_value=fake_client):
        results = await source.fetch([search], db_session)

    assert len(results) == 1
    matched_search, entry = results[0]
    assert matched_search.id == search.id
    assert entry.text == "Looking for a PYTHON developer"
    assert entry.source == "telegram"


@pytest.mark.asyncio
async def test_only_messages_newer_than_last_message_id_are_considered(db_session):
    channel = _channel(db_session, last_message_id=5)
    search = _search(db_session, keywords="python")
    messages = [
        FakeMessage(3, "python dev, old message", FakeSender(10, "Old")),
        FakeMessage(7, "python dev, new message", FakeSender(11, "New")),
    ]
    fake_client = FakeClient(messages)

    source = TelegramSource()
    with patch("app.sources.telegram_source.TelegramClient", return_value=fake_client):
        results = await source.fetch([search], db_session)

    assert len(results) == 1
    assert results[0][1].text == "python dev, new message"

    db_session.refresh(channel)
    assert channel.last_message_id == 7


@pytest.mark.asyncio
async def test_no_channels_skips_client_entirely(db_session):
    search = _search(db_session)
    source = TelegramSource()
    results = await source.fetch([search], db_session)
    assert results == []


@pytest.mark.asyncio
async def test_no_client_call_when_unauthorized(db_session):
    _channel(db_session)
    search = _search(db_session)
    fake_client = FakeClient([])
    fake_client.is_user_authorized = AsyncMock(return_value=False)

    source = TelegramSource()
    with patch("app.sources.telegram_source.TelegramClient", return_value=fake_client):
        results = await source.fetch([search], db_session)

    assert results == []


def test_keyword_matching_is_case_insensitive_substring():
    """The source applies each search's keywords against the shared batch
    of entries fetched from the global channel pool."""
    search = SearchQuery(title="Backend", keywords="python")
    keywords = search.keyword_list()

    assert any(kw in "Looking for a PYTHON developer".lower() for kw in keywords)
    assert not any(kw in "Looking for a marketing manager".lower() for kw in keywords)
