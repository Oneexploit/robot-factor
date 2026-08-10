from __future__ import annotations

import argparse
import asyncio

import uvicorn

from robot_factor.adapters.rubika import RubikaAdapter
from robot_factor.adapters.telegram import TelegramAdapter
from robot_factor.bootstrap import bootstrap_data
from robot_factor.config import get_settings
from robot_factor.db import Database


async def initialize_database() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        await database.create_schema()
        async with database.session_factory() as session:
            await bootstrap_data(session, settings)
    finally:
        await database.dispose()


async def set_webhooks() -> None:
    settings = get_settings()
    if not settings.public_base_url.startswith("https://"):
        raise RuntimeError("PUBLIC_BASE_URL must use HTTPS for production webhooks")
    base = settings.public_base_url
    secret = settings.webhook_path_secret
    if settings.telegram_bot_token:
        telegram = TelegramAdapter(settings.telegram_bot_token)
        try:
            await telegram.set_webhook(
                f"{base}/webhooks/telegram/{secret}", settings.telegram_webhook_secret
            )
            print("Telegram webhook configured")
        finally:
            await telegram.close()
    if settings.rubika_bot_token:
        rubika = RubikaAdapter(settings.rubika_bot_token)
        try:
            await rubika.set_webhooks(
                f"{base}/webhooks/rubika/{secret}/update",
                f"{base}/webhooks/rubika/{secret}/inline",
            )
            print("Rubika webhooks configured")
        finally:
            await rubika.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="robot-factor")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve_parser = subparsers.add_parser("serve", help="run the HTTP service")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", default=8000, type=int)
    subparsers.add_parser("init-db", help="create schema and bootstrap configuration")
    subparsers.add_parser("set-webhooks", help="register Telegram and Rubika webhooks")
    args = parser.parse_args()

    if args.command == "serve":
        uvicorn.run("robot_factor.main:app", host=args.host, port=args.port)
    elif args.command == "init-db":
        asyncio.run(initialize_database())
    elif args.command == "set-webhooks":
        asyncio.run(set_webhooks())


if __name__ == "__main__":
    main()
