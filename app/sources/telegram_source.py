import logging

from sqlalchemy import select
from sqlalchemy.orm import Session
from telethon import TelegramClient
from telethon.errors import RPCError

from app.config import settings
from app.models import SearchQuery, TelegramChannel
from app.sources.base import RawEntry, Source

logger = logging.getLogger(__name__)


class TelegramSource(Source):
    """Collects candidate messages from Telegram channels via the Telegram Client API.

    Requires a pre-authorized Telethon session file (created once via
    scripts/telegram_login.py using the company's Telegram account).
    """

    SOURCE_KEY = "telegram"

    def __init__(self) -> None:
        self._client: TelegramClient | None = None

    async def _get_client(self) -> TelegramClient:
        if self._client is None:
            self._client = TelegramClient(
                settings.telegram_session_path,
                settings.telegram_api_id,
                settings.telegram_api_hash,
            )
        if not self._client.is_connected():
            await self._client.connect()
        return self._client

    async def fetch(self, searches: list[SearchQuery], db: Session) -> list[tuple[SearchQuery, RawEntry]]:
        channels = db.execute(select(TelegramChannel)).scalars().all()
        if not channels:
            return []

        client = await self._get_client()
        if not await client.is_user_authorized():
            logger.error(
                "Telegram session is not authorized. Run scripts/telegram_login.py first."
            )
            return []

        entries: list[RawEntry] = []
        for channel in channels:
            try:
                channel_entries, new_last_id = await self._fetch_channel(client, channel)
            except RPCError:
                logger.exception("Failed to fetch Telegram channel %s", channel.username)
                continue
            if new_last_id is not None:
                channel.last_message_id = new_last_id
                db.add(channel)
            entries.extend(channel_entries)
        db.commit()

        # Channels are shared across searches: match this one batch of freshly
        # fetched entries against every active search's own keywords.
        results: list[tuple[SearchQuery, RawEntry]] = []
        for search in searches:
            keywords = search.keyword_list()
            for entry in entries:
                if not keywords or any(kw in entry.text.lower() for kw in keywords):
                    results.append((search, entry))
        return results

    async def _fetch_channel(
        self, client: TelegramClient, channel: TelegramChannel
    ) -> tuple[list[RawEntry], int | None]:
        entries: list[RawEntry] = []
        min_id = channel.last_message_id or 0
        max_seen_id = channel.last_message_id

        async for message in client.iter_messages(channel.username, min_id=min_id, limit=200):
            if max_seen_id is None or message.id > max_seen_id:
                max_seen_id = message.id

            text = message.message or ""
            if not text:
                continue

            sender = await message.get_sender()
            sender_id = str(sender.id) if sender else None
            sender_name = None
            if sender is not None:
                sender_name = (
                    " ".join(filter(None, [getattr(sender, "first_name", None), getattr(sender, "last_name", None)]))
                    or getattr(sender, "username", None)
                    or sender_id
                )

            link = f"https://t.me/{channel.username.lstrip('@')}/{message.id}"

            entries.append(
                RawEntry(
                    source="telegram",
                    sender_id=sender_id,
                    sender_name=sender_name,
                    text=text,
                    message_link=link,
                    channel=channel.username,
                    posted_at=message.date,
                    external_message_id=message.id,
                )
            )

        return entries, max_seen_id
