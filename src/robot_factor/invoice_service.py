from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from robot_factor.calculator import LineInput, calculate_invoice
from robot_factor.models import (
    AdminUser,
    AuditLog,
    CompanyProfile,
    Customer,
    Invoice,
    InvoiceItem,
    InvoiceStatus,
    InvoiceType,
    PdfStatus,
    Product,
)


class InvoiceNotEditableError(ValueError):
    pass


class InvoiceService:
    async def create_draft(
        self,
        session: AsyncSession,
        *,
        admin: AdminUser,
        platform: str,
        invoice_type: str,
    ) -> Invoice:
        if invoice_type not in {InvoiceType.INVOICE.value, InvoiceType.PROFORMA.value}:
            raise ValueError("invalid invoice type")
        invoice = Invoice(
            invoice_type=invoice_type,
            created_by_admin_id=admin.id,
            created_platform=platform,
            items=[],
        )
        session.add(invoice)
        await session.flush()
        self._audit(session, admin.id, "invoice.draft_created", "invoice", invoice.id)
        return invoice

    async def get_invoice(
        self, session: AsyncSession, invoice_id: int, *, for_update: bool = False
    ) -> Invoice:
        statement = (
            select(Invoice)
            .where(Invoice.id == invoice_id)
            .options(
                selectinload(Invoice.items),
                selectinload(Invoice.customer),
                selectinload(Invoice.created_by),
            )
        )
        if for_update:
            statement = statement.with_for_update()
        invoice = await session.scalar(statement)
        if invoice is None:
            raise LookupError("invoice not found")
        return invoice

    async def attach_customer(
        self,
        session: AsyncSession,
        *,
        invoice: Invoice,
        admin: AdminUser,
        display_name: str,
        phone: str | None,
    ) -> Customer:
        self._ensure_editable(invoice)
        customer: Customer | None = None
        if phone:
            customer = await session.scalar(select(Customer).where(Customer.phone == phone))
        if customer is None:
            customer = Customer(
                display_name=display_name.strip(),
                phone=phone,
                created_by_admin_id=admin.id,
            )
            session.add(customer)
            await session.flush()
            self._audit(session, admin.id, "customer.created", "customer", customer.id)
        invoice.customer_id = customer.id
        invoice.customer = customer
        return customer

    async def add_item(
        self,
        session: AsyncSession,
        *,
        invoice: Invoice,
        product_name: str,
        quantity: Decimal,
        unit: str,
        unit_price: int,
        item_discount: int,
        vat_rate: Decimal,
        product_id: int | None = None,
        description: str | None = None,
    ) -> InvoiceItem:
        self._ensure_editable(invoice)
        product: Product | None = None
        if product_id is not None:
            product = await session.get(Product, product_id)
            if product is None or not product.is_active:
                raise ValueError("selected product is not available")

        position = max((item.position for item in invoice.items), default=0) + 1
        item = InvoiceItem(
            invoice_id=invoice.id,
            product_id=product_id,
            position=position,
            product_name=product_name.strip(),
            description=description,
            quantity=quantity,
            unit=unit.strip(),
            unit_price=unit_price,
            item_discount=item_discount,
            vat_rate=vat_rate,
        )
        invoice.items.append(item)
        session.add(item)
        self.recalculate(invoice)
        await session.flush()
        return item

    async def remove_last_item(self, session: AsyncSession, invoice: Invoice) -> bool:
        self._ensure_editable(invoice)
        if not invoice.items:
            return False
        last_item = max(invoice.items, key=lambda item: item.position)
        invoice.items.remove(last_item)
        await session.delete(last_item)
        if invoice.items:
            self.recalculate(invoice)
        else:
            self._zero_totals(invoice)
        await session.flush()
        return True

    def set_adjustments(
        self,
        invoice: Invoice,
        *,
        invoice_discount: int,
        shipping_cost: int,
        paid_amount: int,
        notes: str | None,
    ) -> None:
        self._ensure_editable(invoice)
        if paid_amount < 0:
            raise ValueError("paid amount cannot be negative")
        invoice.invoice_discount = invoice_discount
        invoice.shipping_cost = shipping_cost
        invoice.paid_amount = paid_amount
        invoice.notes = notes
        self.recalculate(invoice)
        if invoice.paid_amount > invoice.grand_total:
            raise ValueError("paid amount cannot exceed grand total")

    def recalculate(self, invoice: Invoice) -> None:
        totals = calculate_invoice(
            [
                LineInput(
                    quantity=Decimal(item.quantity),
                    unit_price=item.unit_price,
                    item_discount=item.item_discount,
                    vat_rate=Decimal(item.vat_rate),
                )
                for item in invoice.items
            ],
            invoice_discount=invoice.invoice_discount,
            shipping_cost=invoice.shipping_cost,
        )
        for item, line_total in zip(invoice.items, totals.lines, strict=True):
            item.gross_amount = line_total.gross_amount
            item.allocated_invoice_discount = line_total.allocated_invoice_discount
            item.taxable_amount = line_total.taxable_amount
            item.tax_amount = line_total.tax_amount
            item.total_amount = line_total.total_amount
        invoice.subtotal = totals.subtotal
        invoice.item_discount_total = totals.item_discount_total
        invoice.tax_total = totals.tax_total
        invoice.grand_total = totals.grand_total

    async def finalize(
        self, session: AsyncSession, *, invoice: Invoice, admin: AdminUser
    ) -> Invoice:
        self._ensure_editable(invoice)
        if invoice.customer_id is None:
            raise ValueError("customer is required")
        if not invoice.items:
            raise ValueError("at least one item is required")
        self.recalculate(invoice)

        company = await session.scalar(
            select(CompanyProfile).where(CompanyProfile.id == 1).with_for_update()
        )
        if company is None:
            raise RuntimeError("company profile has not been initialized")

        if invoice.invoice_type == InvoiceType.PROFORMA.value:
            sequence = company.next_proforma_sequence
            company.next_proforma_sequence += 1
            prefix = company.proforma_prefix
        else:
            sequence = company.next_invoice_sequence
            company.next_invoice_sequence += 1
            prefix = company.invoice_prefix

        invoice.number = f"{prefix}-{sequence:06d}"
        now = datetime.now(UTC)
        invoice.issue_at = now
        invoice.finalized_at = now
        invoice.status = (
            InvoiceStatus.PAID.value
            if invoice.paid_amount == invoice.grand_total and invoice.grand_total > 0
            else InvoiceStatus.FINAL.value
        )
        invoice.pdf_status = PdfStatus.PENDING.value
        self._audit(
            session,
            admin.id,
            "invoice.finalized",
            "invoice",
            invoice.id,
            {"number": invoice.number, "grand_total": invoice.grand_total},
        )
        await session.flush()
        return invoice

    async def cancel_draft(
        self, session: AsyncSession, *, invoice: Invoice, admin: AdminUser
    ) -> None:
        self._ensure_editable(invoice)
        invoice.status = InvoiceStatus.CANCELED.value
        self._audit(session, admin.id, "invoice.canceled", "invoice", invoice.id)

    async def delete_empty_old_draft(self, session: AsyncSession, invoice_id: int) -> None:
        await session.execute(
            delete(Invoice).where(
                Invoice.id == invoice_id,
                Invoice.status == InvoiceStatus.DRAFT.value,
                ~Invoice.items.any(),
            )
        )

    @staticmethod
    def _ensure_editable(invoice: Invoice) -> None:
        if invoice.status != InvoiceStatus.DRAFT.value:
            raise InvoiceNotEditableError("finalized invoices are immutable")

    @staticmethod
    def _zero_totals(invoice: Invoice) -> None:
        invoice.invoice_discount = 0
        invoice.subtotal = 0
        invoice.item_discount_total = 0
        invoice.tax_total = 0
        invoice.grand_total = invoice.shipping_cost

    @staticmethod
    def _audit(
        session: AsyncSession,
        admin_id: int,
        action: str,
        entity_type: str,
        entity_id: int,
        details: dict[str, object] | None = None,
    ) -> None:
        session.add(
            AuditLog(
                admin_user_id=admin_id,
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id),
                details=details or {},
            )
        )
