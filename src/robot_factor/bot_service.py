from __future__ import annotations

import logging

from robot_factor.conversation import ConversationService
from robot_factor.db import Database
from robot_factor.pdf_service import PdfService
from robot_factor.transport import PlatformAdapter

logger = logging.getLogger(__name__)


class BotService:
    def __init__(
        self,
        database: Database,
        conversation: ConversationService,
        pdf_service: PdfService,
        adapters: dict[str, PlatformAdapter],
    ) -> None:
        self.database = database
        self.conversation = conversation
        self.pdf_service = pdf_service
        self.adapters = adapters

    async def process_payload(
        self, platform: str, payload: dict[str, object], *, event_kind: str = "update"
    ) -> None:
        adapter = self.adapters.get(platform)
        if adapter is None:
            raise RuntimeError(f"{platform} adapter is not configured")
        events = adapter.parse_events(payload, event_kind=event_kind)
        for event in events:
            try:
                await adapter.acknowledge(event)
            except Exception:
                logger.warning("Could not acknowledge callback", exc_info=True)

            async with self.database.session_factory() as session:
                messages = await self.conversation.handle(session, event)
                await session.commit()

            for message in messages:
                outgoing = message
                if message.document_invoice_id is not None:
                    async with self.database.session_factory() as pdf_session:
                        path = await self.pdf_service.render_invoice(
                            pdf_session, message.document_invoice_id
                        )
                    outgoing = type(message)(
                        text=message.text,
                        buttons=message.buttons,
                        document_path=path,
                    )
                await adapter.send(event.chat_id, outgoing)

    async def close(self) -> None:
        for adapter in self.adapters.values():
            await adapter.close()
