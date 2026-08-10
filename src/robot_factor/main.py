from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, status
from sqlalchemy import text

from robot_factor.adapters.rubika import RubikaAdapter
from robot_factor.adapters.telegram import TelegramAdapter
from robot_factor.admin_api import router as admin_router
from robot_factor.bootstrap import bootstrap_data
from robot_factor.bot_service import BotService
from robot_factor.config import Settings, get_settings
from robot_factor.conversation import ConversationService
from robot_factor.db import Database
from robot_factor.invoice_service import InvoiceService
from robot_factor.pdf_service import PdfService

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.validate_runtime_secrets()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    database = Database(settings.database_url)
    invoice_service = InvoiceService()
    pdf_service = PdfService(settings, invoice_service)
    conversation = ConversationService(settings, invoice_service)
    adapters: dict[str, Any] = {}
    if settings.telegram_bot_token:
        adapters["telegram"] = TelegramAdapter(settings.telegram_bot_token)
    if settings.rubika_bot_token:
        adapters["rubika"] = RubikaAdapter(settings.rubika_bot_token)
    bot_service = BotService(database, conversation, pdf_service, adapters)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await database.create_schema()
        async with database.session_factory() as session:
            await bootstrap_data(session, settings)
        settings.invoice_storage_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Robot Factor started; configured adapters: %s", sorted(adapters))
        yield
        await bot_service.close()
        await database.dispose()

    app = FastAPI(
        title="Robot Factor",
        version="0.1.0",
        description="ربات چندسکویی صدور فاکتور فارسی",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.invoice_service = invoice_service
    app.state.pdf_service = pdf_service
    app.state.bot_service = bot_service
    app.state.adapters = adapters
    app.include_router(admin_router)

    @app.get("/healthz", tags=["system"])
    async def health() -> dict[str, object]:
        async with database.session_factory() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok", "adapters": sorted(adapters)}

    @app.post("/webhooks/telegram/{path_secret}", include_in_schema=False)
    async def telegram_webhook(
        path_secret: str,
        request: Request,
        x_telegram_bot_api_secret_token: str = Header(
            default="", alias="X-Telegram-Bot-Api-Secret-Token"
        ),
    ) -> dict[str, bool]:
        if not hmac.compare_digest(path_secret, settings.webhook_path_secret):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if not hmac.compare_digest(
            x_telegram_bot_api_secret_token, settings.telegram_webhook_secret
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if "telegram" not in adapters:
            raise HTTPException(status_code=503, detail="Telegram adapter is disabled")
        payload = await request.json()
        await bot_service.process_payload("telegram", payload)
        return {"ok": True}

    @app.post("/webhooks/rubika/{path_secret}/{event_kind}", include_in_schema=False)
    async def rubika_webhook(
        path_secret: str,
        event_kind: str,
        request: Request,
    ) -> dict[str, bool]:
        if not hmac.compare_digest(path_secret, settings.webhook_path_secret):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if event_kind not in {"update", "inline"}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if "rubika" not in adapters:
            raise HTTPException(status_code=503, detail="Rubika adapter is disabled")
        payload = await request.json()
        await bot_service.process_payload("rubika", payload, event_kind=event_kind)
        return {"ok": True}

    return app


app = create_app()
