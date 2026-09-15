from sqlalchemy import select

from app.models import SearchQuery, SearchStatus, TelegramChannel


def test_create_search(logged_in_client, SessionTest):
    client, _ = logged_in_client
    resp = client.post(
        "/searches",
        data={"title": "Python Developer", "keywords": "python, django"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    session = SessionTest()
    search = session.execute(select(SearchQuery)).scalar_one()
    assert search.title == "Python Developer"
    assert search.status == SearchStatus.active
    session.close()


def test_create_search_with_no_sources_selected_means_all(logged_in_client, SessionTest):
    client, _ = logged_in_client
    client.post("/searches", data={"title": "Any Source", "keywords": "python"})

    session = SessionTest()
    search = session.execute(select(SearchQuery)).scalar_one()
    assert search.sources == ""
    assert search.source_keys() == []
    assert search.runs_on_source("telegram") is True
    assert search.runs_on_source("hh_api") is True
    session.close()


def test_create_search_with_selected_sources(logged_in_client, SessionTest):
    client, _ = logged_in_client
    client.post(
        "/searches",
        data={"title": "Scoped", "keywords": "python", "sources": ["telegram", "hh_api"]},
    )

    session = SessionTest()
    search = session.execute(select(SearchQuery)).scalar_one()
    assert set(search.source_keys()) == {"telegram", "hh_api"}
    assert search.runs_on_source("telegram") is True
    assert search.runs_on_source("hh_api") is True
    assert search.runs_on_source("linkedin") is False
    session.close()


def test_create_search_ignores_unknown_source_keys(logged_in_client, SessionTest):
    client, _ = logged_in_client
    client.post(
        "/searches",
        data={"title": "Bogus", "keywords": "python", "sources": ["telegram", "not-a-real-source"]},
    )

    session = SessionTest()
    search = session.execute(select(SearchQuery)).scalar_one()
    assert search.source_keys() == ["telegram"]
    session.close()


def test_searches_page_shows_source_selection(logged_in_client):
    client, _ = logged_in_client
    client.post("/searches", data={"title": "Scoped", "keywords": "python", "sources": ["linkedin"]})

    resp = client.get("/searches")
    assert resp.status_code == 200
    assert "LinkedIn" in resp.text


def test_list_searches_shows_created(logged_in_client):
    client, _ = logged_in_client
    client.post("/searches", data={"title": "Backend Dev", "keywords": "python"})
    resp = client.get("/searches")
    assert resp.status_code == 200
    assert "Backend Dev" in resp.text


def test_toggle_search_status(logged_in_client, SessionTest):
    client, _ = logged_in_client
    client.post("/searches", data={"title": "QA", "keywords": "qa, test"})
    session = SessionTest()
    search = session.execute(select(SearchQuery)).scalar_one()
    search_id = search.id
    session.close()

    resp = client.post(f"/searches/{search_id}/status", data={"status": "paused"}, follow_redirects=False)
    assert resp.status_code == 303

    session = SessionTest()
    search = session.get(SearchQuery, search_id)
    assert search.status == SearchStatus.paused
    session.close()


def test_add_and_remove_channel(logged_in_client, SessionTest):
    client, _ = logged_in_client

    resp = client.post("/channels", data={"username": "@some_channel"}, follow_redirects=False)
    assert resp.status_code == 303

    session = SessionTest()
    channel = session.execute(select(TelegramChannel)).scalar_one()
    assert channel.username == "some_channel"  # leading @ stripped
    channel_id = channel.id
    session.close()

    resp = client.post(f"/channels/{channel_id}/delete", follow_redirects=False)
    assert resp.status_code == 303

    session = SessionTest()
    remaining = session.execute(select(TelegramChannel)).scalars().all()
    assert remaining == []
    session.close()


def test_duplicate_channel_shows_error(logged_in_client, SessionTest):
    client, _ = logged_in_client
    client.post("/channels", data={"username": "some_channel"})

    resp = client.post("/channels", data={"username": "Some_Channel"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/channels?error=duplicate"

    resp = client.get("/channels?error=duplicate")
    assert "уже есть в списке" in resp.text

    session = SessionTest()
    count = len(session.execute(select(TelegramChannel)).scalars().all())
    session.close()
    assert count == 1


def test_channel_is_global_across_searches(logged_in_client, SessionTest):
    client, _ = logged_in_client
    client.post("/searches", data={"title": "Design", "keywords": "figma"})
    client.post("/searches", data={"title": "Backend", "keywords": "python"})
    client.post("/channels", data={"username": "shared_channel"})

    resp = client.get("/channels")
    assert resp.status_code == 200
    assert "shared_channel" in resp.text
