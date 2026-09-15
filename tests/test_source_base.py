import pytest

from app.sources.base import RawEntry, Source


def test_source_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        Source()


def test_source_subclass_without_fetch_cannot_be_instantiated():
    class Incomplete(Source):
        pass

    with pytest.raises(TypeError):
        Incomplete()


def test_source_subclass_with_fetch_can_be_instantiated():
    class Complete(Source):
        async def fetch(self, search, db):
            return []

    instance = Complete()
    assert isinstance(instance, Source)


def test_raw_entry_is_a_plain_dataclass_with_expected_fields():
    from datetime import datetime, timezone

    entry = RawEntry(
        sender_id="1",
        sender_name="Ivan",
        text="hello",
        message_link="https://t.me/x/1",
        channel="x",
        posted_at=datetime.now(timezone.utc),
    )
    assert entry.external_message_id is None
