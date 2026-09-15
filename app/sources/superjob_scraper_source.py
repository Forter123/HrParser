import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlencode, urljoin

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import SearchQuery, SourceSeenEntry
from app.sources.base import RawEntry, Source

logger = logging.getLogger(__name__)

BASE_URL = "https://www.superjob.ru"
SEARCH_URL = f"{BASE_URL}/resume/search_resume.html"

RESUME_LINK_RE = re.compile(r"/resume/[^/]+-(\d+)\.html")
RESUME_LINK_SELECTOR = 'a[href*="/resume/"]'
INITIAL_WAIT_MS = 8000

# Best-effort markers for "this is a captcha/anti-bot challenge page", checked
# case-insensitively against the page's rendered text. Not exhaustive — add to
# this if SuperJob shows a different challenge and it's slipping through.
CAPTCHA_MARKERS = [
    "captcha",
    "капч",
    "не робот",
    "подтвердите, что вы человек",
    "smartcaptcha",
    "recaptcha",
]


class SuperJobScraperSource(Source):
    """Fallback SuperJob candidate source: drives a browser profile in the
    Vision antidetect browser (https://browser.vision) against the public
    resume search page, instead of calling the official (paid) api.superjob.ru.

    ONLY ACTIVE IF `settings.vision_profile_id` IS SET — same pattern as every
    other source (Telegram/SuperJob/LinkedIn/HH all activate purely based on
    having credentials configured, no separate on/off flag). Off by default
    simply because `vision_profile_id` is empty by default. Read this before
    filling it in:

    1. Legal/ToS risk: this bypasses SuperJob's official API and its paid
       licensing (see the price list: API access alone runs ~72,000 RUB/month
       as of the 2026-08-03 SuperJob price list). Automating a browser
       against the public site — even one designed to resist fingerprinting —
       still likely violates SuperJob's terms of service. Risk: the Vision
       profile (and whatever IP it uses) getting blocked, and a weaker legal
       position than a licensed API user if SuperJob ever objects.
    2. Personal data (152-FZ) risk — the more important one: resumes contain
       personal data of real people. Under Russian law (152-FZ), collecting
       and storing personal data without a legal basis/consent is a
       compliance problem for your company as the data operator, regardless
       of whether the scraping itself is "allowed" by SuperJob. To reduce
       this:
       - This scraper intentionally only extracts what SuperJob already shows
         to anonymous, logged-out visitors on the SEARCH RESULTS page (title,
         city, salary, a resume URL) — it does NOT log in, does NOT follow
         through to the full resume page, and does NOT attempt to extract
         phone numbers, birth dates, or full unmasked names.
       - Get a legal/compliance sign-off before enabling this in production.
       - If someone is later tempted to add a real employer login here to see
         full (unmasked) resumes — don't, without a separate legal review
         first. That's a materially bigger 152-FZ exposure than this.
    3. Why a real (antidetect) browser instead of a plain HTTP request:
       SuperJob's search results may be client-rendered (filled in by
       JavaScript after the page loads), which a plain `httpx` GET can't see
       — only a real browser executing the page's JS can. Vision specifically
       (rather than a bare Playwright-launched Chromium) gives each profile
       its own persistent, isolated browser fingerprint, which is harder for
       SuperJob's bot detection to distinguish from a real visitor than a
       vanilla automated Chromium instance.
    4. Dedicated Vision profile: this is meant to run against a Vision
       profile created specifically for this purpose (`vision_folder_id` /
       `vision_profile_id`) — separate from anyone's personal browsing
       profile, so its cookies/fingerprint/history build up independently.
       Vision itself controls whether that profile's window is visible or
       not — see the Vision app settings, not this code.
    5. Fragile by construction: `_parse_results`' selectors are best-effort,
       guessed from public information rather than verified against
       SuperJob's actual live markup (no direct internet access when this
       was authored). Verify against a real page and adjust before relying
       on this, and expect to maintain it as SuperJob's markup changes.

    How it connects: Vision runs as a local app exposing an HTTP control API
    (default `http://127.0.0.1:3030`, see docs.browser.vision). This source:
      1. Calls `GET /start/{folder_id}/{profile_id}` to launch the dedicated
         profile — Vision replies with the CDP debugging `port` it started on
         (a profile must be started through this API to be automatable; one
         opened by hand in the Vision app isn't attachable this way).
      2. Connects Playwright to that running browser via
         `chromium.connect_over_cdp(f"http://127.0.0.1:{port}")` — Playwright
         drives the *existing* Vision browser window rather than launching
         its own.
      3. Calls `GET /stop/{folder_id}/{profile_id}` when done, once per
         `fetch()` cycle, to free the profile up (and avoid it running
         indefinitely on the machine unattended).
    Requires: the Vision app installed and running, with `vision_folder_id`
    and `vision_profile_id` pointing at a profile created for this purpose in
    the Vision app first (this code cannot create a Vision profile itself).
    """

    SOURCE_KEY = "superjob_scraper"

    def __init__(self) -> None:
        self._api_base = f"http://{settings.vision_api_host}:{settings.vision_api_port}"

    def _is_configured(self) -> bool:
        return bool(settings.vision_profile_id)

    def _vision_headers(self) -> dict:
        headers = {}
        if settings.vision_api_token:
            headers["X-Token"] = settings.vision_api_token
        return headers

    async def fetch(self, searches: list[SearchQuery], db: Session) -> list[tuple[SearchQuery, RawEntry]]:
        if not self._is_configured():
            return []

        results: list[tuple[SearchQuery, RawEntry]] = []

        async with httpx.AsyncClient(headers=self._vision_headers(), timeout=20) as vision_client:
            cdp_port = await self._start_vision_profile(vision_client)
            if cdp_port is None:
                return []

            try:
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.connect_over_cdp(
                        f"http://127.0.0.1:{cdp_port}"
                    )
                    try:
                        context = browser.contexts[0] if browser.contexts else await browser.new_context()
                        page = await context.new_page()
                        captcha_state = {"handled": False}
                        try:
                            for search in searches:
                                keywords = search.keyword_list()
                                if not keywords:
                                    continue
                                try:
                                    resumes = await self._search_resumes(page, keywords, captcha_state)
                                except PlaywrightError:
                                    logger.exception(
                                        "Failed to scrape SuperJob resumes for search %s", search.id
                                    )
                                    continue

                                for resume in resumes:
                                    external_id = resume["external_id"]
                                    if self._already_seen(db, search.id, external_id):
                                        continue
                                    results.append((search, self._to_raw_entry(resume)))
                                    self._mark_seen(db, search.id, external_id)
                        finally:
                            await page.close()
                    finally:
                        await browser.close()
            finally:
                await self._stop_vision_profile(vision_client)

        db.commit()
        return results

    async def _start_vision_profile(self, client: httpx.AsyncClient) -> int | None:
        url = f"{self._api_base}/start/{settings.vision_folder_id}/{settings.vision_profile_id}"
        resp = None
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            return int(data["port"])
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            logger.exception(
                "Failed to start Vision profile %s/%s — is the Vision app running? "
                "Response body: %s",
                settings.vision_folder_id,
                settings.vision_profile_id,
                resp.text if resp is not None else "<no response>",
            )
            return None

    async def _stop_vision_profile(self, client: httpx.AsyncClient) -> None:
        url = f"{self._api_base}/stop/{settings.vision_folder_id}/{settings.vision_profile_id}"
        try:
            await client.get(url)
        except httpx.HTTPError:
            logger.exception(
                "Failed to stop Vision profile %s/%s", settings.vision_folder_id, settings.vision_profile_id
            )

    async def _search_resumes(self, page, keywords: list[str], captcha_state: dict) -> list[dict]:
        url = f"{SEARCH_URL}?{urlencode({'keywords': ' '.join(keywords)})}"
        await page.goto(url, wait_until="domcontentloaded")
        try:
            await page.wait_for_selector(RESUME_LINK_SELECTOR, timeout=INITIAL_WAIT_MS)
            html = await page.content()
        except PlaywrightError:
            # No results within the fast path — check whether it's actually a
            # captcha/anti-bot challenge before giving up. If so, give a human
            # real time to solve it in the visible Vision window instead of
            # abandoning after 8 seconds. Only do this once per fetch() cycle:
            # once cleared, the same browser session should stay clear for the
            # rest of this cycle's searches, and there's no point waiting the
            # full timeout again for every single search if it isn't.
            html = await page.content()
            if not captcha_state["handled"] and self._looks_like_captcha(html):
                captcha_state["handled"] = True
                await self._wait_for_captcha_to_clear(page)
                # Re-fetch: the page navigated/changed while we waited.
                html = await page.content()
            # Otherwise: either a genuine no-results page, or the captcha
            # timeout expired without being solved — `html` here is still the
            # (captcha/empty) page, and _parse_results will return [] for it.

        return self._parse_results(html)

    def _looks_like_captcha(self, html: str) -> bool:
        lowered = html.lower()
        return any(marker in lowered for marker in CAPTCHA_MARKERS)

    async def _wait_for_captcha_to_clear(self, page) -> None:
        wait_seconds = settings.superjob_captcha_wait_seconds
        logger.warning(
            "SuperJob showed a captcha/anti-bot challenge. Open the Vision "
            "browser window for this profile and solve it manually — waiting "
            "up to %d seconds before giving up on this search.",
            wait_seconds,
        )
        try:
            await page.wait_for_selector(RESUME_LINK_SELECTOR, timeout=wait_seconds * 1000)
            logger.info("Captcha cleared, continuing.")
        except PlaywrightError:
            logger.warning(
                "Captcha was not solved within %d seconds — skipping this search "
                "for the current poll cycle.",
                wait_seconds,
            )

    def _parse_results(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        resumes: list[dict] = []

        # Best-effort: SuperJob resume cards on the search page. Try a couple
        # of plausible selector shapes since the real markup wasn't verified
        # live — adjust these to match the actual page if they don't match.
        cards = soup.select('[class*="resume"] a[href*="/resume/"]') or soup.find_all(
            "a", href=RESUME_LINK_RE
        )

        seen_links = set()
        for link_tag in cards:
            href = link_tag.get("href") or ""
            match = RESUME_LINK_RE.search(href)
            if not match:
                continue
            full_url = urljoin(BASE_URL, href)
            if full_url in seen_links:
                continue
            seen_links.add(full_url)

            card = link_tag.find_parent(["div", "li", "article"]) or link_tag
            title = link_tag.get_text(" ", strip=True) or "Без названия"
            card_text = card.get_text(" ", strip=True)

            resumes.append(
                {
                    "external_id": match.group(1),
                    "title": title,
                    "card_text": card_text,
                    "url": full_url,
                }
            )

        return resumes

    def _already_seen(self, db: Session, search_id: int, external_id: str) -> bool:
        existing = db.execute(
            select(SourceSeenEntry).where(
                SourceSeenEntry.source == "superjob",
                SourceSeenEntry.search_query_id == search_id,
                SourceSeenEntry.external_id == external_id,
            )
        ).scalar_one_or_none()
        return existing is not None

    def _mark_seen(self, db: Session, search_id: int, external_id: str) -> None:
        db.add(SourceSeenEntry(source="superjob", search_query_id=search_id, external_id=external_id))

    def _to_raw_entry(self, resume: dict) -> RawEntry:
        return RawEntry(
            source="superjob",
            sender_id=resume["external_id"],
            sender_name=resume["title"],
            text=resume["card_text"],
            message_link=resume["url"],
            channel="superjob",
            posted_at=datetime.now(timezone.utc),
            external_message_id=resume["external_id"],
        )
