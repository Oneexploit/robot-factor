from __future__ import annotations

from sqlalchemy import select

from robot_factor.conversation import ConversationService
from robot_factor.invoice_service import InvoiceService
from robot_factor.models import Invoice, InvoiceStatus
from robot_factor.transport import IncomingEvent


async def test_complete_invoice_conversation(app_context) -> None:
    settings, database = app_context
    service = ConversationService(settings, InvoiceService())
    counter = 0

    async def send(text: str, callback: bool = False):
        nonlocal counter
        counter += 1
        event = IncomingEvent(
            platform="telegram",
            update_id=str(counter),
            chat_id="1001",
            user_id="1001",
            text=text,
            callback_data=text if callback else None,
        )
        async with database.session_factory() as session:
            result = await service.handle(session, event)
            await session.commit()
            return result

    await send("new:invoice", callback=True)
    await send("فروشگاه نمونه")
    await send("-")
    await send("product:manual", callback=True)
    await send("زغال لیمو ممتاز")
    await send("10")
    await send("کارتن")
    await send("250000")
    await send("0")
    await send("10")
    await send("adjustments", callback=True)
    await send("100000")
    await send("50000")
    await send("500000")
    await send("تحویل درب انبار")
    result = await send("finalize", callback=True)

    document_messages = [message for message in result if message.document_invoice_id]
    assert len(document_messages) == 1
    async with database.session_factory() as session:
        invoice = await session.scalar(select(Invoice))
        assert invoice is not None
        assert invoice.status == InvoiceStatus.FINAL.value
        assert invoice.number == "INV-000001"
        assert invoice.grand_total == 2_690_000
        assert invoice.balance_due == 2_190_000


async def test_denies_unknown_user(app_context) -> None:
    settings, database = app_context
    service = ConversationService(settings, InvoiceService())
    async with database.session_factory() as session:
        result = await service.handle(
            session,
            IncomingEvent(
                platform="telegram",
                update_id="unknown-1",
                chat_id="9999",
                user_id="9999",
                text="/start",
            ),
        )
        await session.commit()
    assert "دسترسی" in result[0].text
