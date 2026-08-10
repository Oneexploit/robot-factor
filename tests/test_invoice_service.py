from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from robot_factor.invoice_service import InvoiceNotEditableError, InvoiceService
from robot_factor.models import AdminUser, InvoiceType


async def test_finalized_invoice_is_immutable(app_context) -> None:
    _, database = app_context
    service = InvoiceService()
    async with database.session_factory() as session:
        admin = await session.scalar(select(AdminUser).where(AdminUser.platform == "telegram"))
        invoice = await service.create_draft(
            session,
            admin=admin,
            platform="telegram",
            invoice_type=InvoiceType.INVOICE.value,
        )
        await service.attach_customer(
            session,
            invoice=invoice,
            admin=admin,
            display_name="مشتری تست",
            phone=None,
        )
        await service.add_item(
            session,
            invoice=invoice,
            product_name="زغال تست",
            quantity=Decimal("1"),
            unit="کارتن",
            unit_price=100,
            item_discount=0,
            vat_rate=Decimal("0"),
        )
        await service.finalize(session, invoice=invoice, admin=admin)
        with pytest.raises(InvoiceNotEditableError):
            await service.add_item(
                session,
                invoice=invoice,
                product_name="نباید ثبت شود",
                quantity=Decimal("1"),
                unit="عدد",
                unit_price=1,
                item_discount=0,
                vat_rate=Decimal("0"),
            )
