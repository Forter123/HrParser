import httpx
import pytest

from app.models import SearchQuery, SourceSeenEntry
from app.sources.superjob_scraper_source import SuperJobScraperSource

SAMPLE_HTML = """
<html><body>
<div class="resume-serp-item">
  <a href="/resume/programmist-python-555.html">Иван В., Python-разработчик</a>
  <div>Москва &middot; 150 000 руб.</div>
</div>
</body></html>
"""

CAPTCHA_HTML = """
<html><body>
<div class="captcha-container">Подтвердите, что вы человек. Введите капчу.</div>
</body></html>
"""


def _search(db_session, keywords="python"):
    search = SearchQuery(title="Backend", keywords=keywords)
    db_session.add(search)
    db_session.commit()
    db_session.refresh(search)
    return search


def _configure(monkeypatch):
    monkeypatch.setattr("app.sources.superjob_scraper_source.settings.vision_folder_id", "folder1")
    monkeypatch.setattr("app.sources.superjob_scraper_source.settings.vision_profile_id", "profile1")


# ---- Vision local API fakes ----


class FakeVisionResponse:
    def __init__(self, json_data=None, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class FakeVisionClient:
    def __init__(self, start_response, fail_start=False):
        self._start_response = start_response
        self._fail_start = fail_start
        self.get_calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        self.get_calls.append(url)
        if "/start/" in url:
            if self._fail_start:
                raise httpx.ConnectError("Vision app not running")
            return FakeVisionResponse(self._start_response)
        return FakeVisionResponse({})


# ---- Playwright (CDP) fakes ----


class FakePage:
    def __init__(self, htmls, fail_wait_for_selector=False, wait_for_selector_outcomes=None):
        self._htmls = list(htmls)
        self.goto_calls = []
        self.wait_for_selector_calls = 0
        self.closed = False
        self._fail_wait_for_selector = fail_wait_for_selector
        # If given, a list of bool (True=succeed, False=raise) consumed one
        # per wait_for_selector call, for tests that need fine control over
        # which specific call succeeds (e.g. the captcha-clears-on-retry case).
        self._outcomes = list(wait_for_selector_outcomes) if wait_for_selector_outcomes is not None else None

    async def goto(self, url, wait_until=None):
        self.goto_calls.append(url)

    async def wait_for_selector(self, selector, timeout=None):
        self.wait_for_selector_calls += 1
        if self._outcomes is not None:
            succeeds = self._outcomes.pop(0) if self._outcomes else True
            if not succeeds:
                from playwright.async_api import Error as PlaywrightError

                raise PlaywrightError("timeout")
            return None
        if self._fail_wait_for_selector:
            from playwright.async_api import Error as PlaywrightError

            raise PlaywrightError("timeout")

    async def content(self):
        return self._htmls.pop(0)

    async def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, page):
        self._page = page

    async def new_page(self):
        return self._page


class FakeBrowser:
    def __init__(self, page):
        self.contexts = [FakeContext(page)]
        self.closed = False

    async def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, browser):
        self._browser = browser
        self.connect_calls = []

    async def connect_over_cdp(self, endpoint_url):
        self.connect_calls.append(endpoint_url)
        return self._browser


class FakePlaywright:
    def __init__(self, chromium):
        self.chromium = chromium

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _install_fakes(monkeypatch, page, start_response=None, fail_start=False):
    if start_response is None:
        start_response = {"folder_id": "folder1", "profile_id": "profile1", "port": 19512}

    vision_client = FakeVisionClient(start_response, fail_start=fail_start)
    monkeypatch.setattr(
        "app.sources.superjob_scraper_source.httpx.AsyncClient", lambda **kw: vision_client
    )

    browser = FakeBrowser(page)
    chromium = FakeChromium(browser)
    monkeypatch.setattr(
        "app.sources.superjob_scraper_source.async_playwright", lambda: FakePlaywright(chromium)
    )
    return vision_client, browser, chromium


@pytest.mark.asyncio
async def test_returns_empty_when_vision_profile_not_set(db_session):
    # vision_profile_id left empty (default) — no separate enable flag needed
    source = SuperJobScraperSource()
    results = await source.fetch([_search(db_session)], db_session)
    assert results == []


@pytest.mark.asyncio
async def test_fetch_starts_vision_profile_connects_and_parses_results(db_session, monkeypatch):
    _configure(monkeypatch)
    search = _search(db_session, keywords="python")

    page = FakePage([SAMPLE_HTML])
    vision_client, browser, chromium = _install_fakes(monkeypatch, page)

    source = SuperJobScraperSource()
    results = await source.fetch([search], db_session)

    assert len(results) == 1
    matched_search, entry = results[0]
    assert matched_search.id == search.id
    assert entry.source == "superjob"
    assert entry.sender_id == "555"
    assert entry.message_link == "https://www.superjob.ru/resume/programmist-python-555.html"
    assert "Python-разработчик" in entry.sender_name

    assert vision_client.get_calls[0] == "http://127.0.0.1:3030/start/folder1/profile1"
    assert chromium.connect_calls == ["http://127.0.0.1:19512"]
    assert vision_client.get_calls[-1] == "http://127.0.0.1:3030/stop/folder1/profile1"
    assert browser.closed is True
    assert page.closed is True


@pytest.mark.asyncio
async def test_returns_empty_when_vision_profile_fails_to_start(db_session, monkeypatch):
    _configure(monkeypatch)
    search = _search(db_session, keywords="python")

    page = FakePage([SAMPLE_HTML])
    vision_client, browser, chromium = _install_fakes(monkeypatch, page, fail_start=True)

    source = SuperJobScraperSource()
    results = await source.fetch([search], db_session)

    assert results == []
    assert chromium.connect_calls == []


@pytest.mark.asyncio
async def test_already_seen_resume_is_not_returned_again(db_session, monkeypatch):
    _configure(monkeypatch)
    search = _search(db_session, keywords="python")
    db_session.add(SourceSeenEntry(source="superjob", search_query_id=search.id, external_id="555"))
    db_session.commit()

    page = FakePage([SAMPLE_HTML])
    _install_fakes(monkeypatch, page)

    source = SuperJobScraperSource()
    results = await source.fetch([search], db_session)

    assert results == []


@pytest.mark.asyncio
async def test_search_without_keywords_is_skipped(db_session, monkeypatch):
    _configure(monkeypatch)
    search = SearchQuery(title="Empty", keywords="")
    db_session.add(search)
    db_session.commit()
    db_session.refresh(search)

    page = FakePage([])
    _install_fakes(monkeypatch, page)

    source = SuperJobScraperSource()
    results = await source.fetch([search], db_session)

    assert results == []
    assert page.goto_calls == []


@pytest.mark.asyncio
async def test_no_resume_links_in_html_returns_empty(db_session, monkeypatch):
    _configure(monkeypatch)
    search = _search(db_session, keywords="python")

    page = FakePage(
        ["<html><body><p>Ничего не найдено</p></body></html>"], fail_wait_for_selector=True
    )
    _install_fakes(monkeypatch, page)

    source = SuperJobScraperSource()
    results = await source.fetch([search], db_session)

    assert results == []


@pytest.mark.asyncio
async def test_captcha_detected_and_cleared_after_manual_solve(db_session, monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr("app.sources.superjob_scraper_source.settings.superjob_captcha_wait_seconds", 1)
    search = _search(db_session, keywords="python")

    page = FakePage(
        [CAPTCHA_HTML, SAMPLE_HTML],
        wait_for_selector_outcomes=[False, True],  # fast wait fails, long wait succeeds
    )
    _install_fakes(monkeypatch, page)

    source = SuperJobScraperSource()
    results = await source.fetch([search], db_session)

    assert len(results) == 1
    assert results[0][1].sender_id == "555"
    assert page.wait_for_selector_calls == 2


@pytest.mark.asyncio
async def test_captcha_not_solved_in_time_gives_up_for_that_search(db_session, monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr("app.sources.superjob_scraper_source.settings.superjob_captcha_wait_seconds", 1)
    search = _search(db_session, keywords="python")

    page = FakePage(
        [CAPTCHA_HTML, CAPTCHA_HTML],
        wait_for_selector_outcomes=[False, False],  # fast wait fails, long wait also fails
    )
    _install_fakes(monkeypatch, page)

    source = SuperJobScraperSource()
    results = await source.fetch([search], db_session)

    assert results == []
    assert page.wait_for_selector_calls == 2


@pytest.mark.asyncio
async def test_captcha_long_wait_only_triggered_once_per_fetch_cycle(db_session, monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr("app.sources.superjob_scraper_source.settings.superjob_captcha_wait_seconds", 1)
    search1 = _search(db_session, keywords="python")
    search2 = _search(db_session, keywords="java")

    page = FakePage(
        [CAPTCHA_HTML, CAPTCHA_HTML, CAPTCHA_HTML],
        wait_for_selector_outcomes=[False, False, False],
    )
    _install_fakes(monkeypatch, page)

    source = SuperJobScraperSource()
    results = await source.fetch([search1, search2], db_session)

    assert results == []
    # search1: fast wait + long wait = 2 attempts. search2: fast wait only = 1
    # attempt (no second long wait, since the cycle already gave up on it).
    assert page.wait_for_selector_calls == 3
