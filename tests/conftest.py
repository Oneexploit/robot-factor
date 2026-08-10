from __future__ import annotations

from pathlib import Path

import pytest_asyncio

from robot_factor.bootstrap import bootstrap_data
from robot_factor.config import Settings
from robot_factor.db import Database


@pytest_asyncio.fixture
async def app_context(tmp_path: Path):
    settings = Settings(
        DATABASE_URL=f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
        ADMIN_IDENTITIES="telegram:1001,rubika:u-test",
        INVOICE_STORAGE_DIR=tmp_path / "invoices",
        ADMIN_API_KEY="test-admin-key",
    )
    database = Database(settings.database_url)
    await database.create_schema()
    async with database.session_factory() as session:
        await bootstrap_data(session, settings)
    try:
        yield settings, database
    finally:
        await database.dispose()
