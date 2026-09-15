"""One-off interactive login to create a Telethon session file for the company
Telegram account. Run once (locally, not in CI): python scripts/telegram_login.py
It will prompt for phone number, code, and (if enabled) 2FA password, then save
the session to settings.telegram_session_path for the worker to reuse.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telethon import TelegramClient

from app.config import settings


async def main() -> None:
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        print("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first (get them at my.telegram.org).")
        return

    client = TelegramClient(settings.telegram_session_path, settings.telegram_api_id, settings.telegram_api_hash)
    await client.start()
    me = await client.get_me()
    print(f"Logged in as {me.first_name} ({me.phone}). Session saved to {settings.telegram_session_path}.session")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
