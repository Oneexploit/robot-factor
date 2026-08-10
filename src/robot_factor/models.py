from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Platform(StrEnum):
    TELEGRAM = "telegram"
    RUBIKA = "rubika"


class CustomerKind(StrEnum):
    INDIVIDUAL = "individual"
    BUSINESS = "business"


class InvoiceType(StrEnum):
    INVOICE = "invoice"
    PROFORMA = "proforma"


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    FINAL = "final"
    PAID = "paid"
    VOID = "void"
    CANCELED = "canceled"


class PdfStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class AdminUser(Base, TimestampMixin):
    __tablename__ = "admin_users"
    __table_args__ = (
        UniqueConstraint("platform", "external_user_id", name="uq_admin_platform_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    external_user_id: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(200), default="مدیر")
    partner_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CompanyProfile(Base, TimestampMixin):
    __tablename__ = "company_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    brand_name: Mapped[str] = mapped_column(String(200), default="فروشگاه زغال")
    legal_name: Mapped[str | None] = mapped_column(String(250), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    website: Mapped[str | None] = mapped_column(String(250), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    national_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    registration_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    economic_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    card_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    iban: Mapped[str | None] = mapped_column(String(34), nullable=True)
    account_holder: Mapped[str | None] = mapped_column(String(200), nullable=True)
    logo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    stamp_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    footer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    money_unit: Mapped[str] = mapped_column(String(16), default="تومان")
    default_vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    invoice_prefix: Mapped[str] = mapped_column(String(32), default="INV")
    proforma_prefix: Mapped[str] = mapped_column(String(32), default="PRO")
    next_invoice_sequence: Mapped[int] = mapped_column(Integer, default=1)
    next_proforma_sequence: Mapped[int] = mapped_column(Integer, default=1)


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default=CustomerKind.INDIVIDUAL.value)
    display_name: Mapped[str] = mapped_column(String(250), index=True)
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    national_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    economic_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True
    )


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(250), index=True)
    grade: Mapped[str | None] = mapped_column(String(100), nullable=True)
    packaging: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[str] = mapped_column(String(32), default="کیلوگرم")
    weight_per_package: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    default_unit_price: Mapped[int] = mapped_column(BigInteger, default=0)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("number", name="uq_invoice_number"),
        Index("ix_invoice_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    invoice_type: Mapped[str] = mapped_column(String(20), default=InvoiceType.INVOICE.value)
    status: Mapped[str] = mapped_column(String(20), default=InvoiceStatus.DRAFT.value)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    created_by_admin_id: Mapped[int] = mapped_column(
        ForeignKey("admin_users.id", ondelete="RESTRICT"), index=True
    )
    created_platform: Mapped[str] = mapped_column(String(20))
    issue_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    invoice_discount: Mapped[int] = mapped_column(BigInteger, default=0)
    shipping_cost: Mapped[int] = mapped_column(BigInteger, default=0)
    subtotal: Mapped[int] = mapped_column(BigInteger, default=0)
    item_discount_total: Mapped[int] = mapped_column(BigInteger, default=0)
    tax_total: Mapped[int] = mapped_column(BigInteger, default=0)
    grand_total: Mapped[int] = mapped_column(BigInteger, default=0)
    paid_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_status: Mapped[str] = mapped_column(String(20), default=PdfStatus.NOT_REQUESTED.value)
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pdf_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True
    )

    customer: Mapped[Customer | None] = relationship(lazy="selectin")
    created_by: Mapped[AdminUser] = relationship(lazy="selectin")
    items: Mapped[list[InvoiceItem]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="InvoiceItem.position",
    )

    @property
    def balance_due(self) -> int:
        return max(0, (self.grand_total or 0) - (self.paid_amount or 0))


class InvoiceItem(Base, TimestampMixin):
    __tablename__ = "invoice_items"
    __table_args__ = (UniqueConstraint("invoice_id", "position", name="uq_invoice_item_pos"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer)
    product_name: Mapped[str] = mapped_column(String(250))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    unit: Mapped[str] = mapped_column(String(32))
    unit_price: Mapped[int] = mapped_column(BigInteger)
    item_discount: Mapped[int] = mapped_column(BigInteger, default=0)
    allocated_invoice_discount: Mapped[int] = mapped_column(BigInteger, default=0)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    gross_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    taxable_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    tax_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    total_amount: Mapped[int] = mapped_column(BigInteger, default=0)

    invoice: Mapped[Invoice] = relationship(back_populates="items")


class ConversationSession(Base, TimestampMixin):
    __tablename__ = "conversation_sessions"
    __table_args__ = (
        UniqueConstraint(
            "platform", "chat_id", "external_user_id", name="uq_conversation_identity"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(20))
    chat_id: Mapped[str] = mapped_column(String(128))
    external_user_id: Mapped[str] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(64), default="idle")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProcessedUpdate(Base):
    __tablename__ = "processed_updates"
    __table_args__ = (
        UniqueConstraint("platform", "update_id", name="uq_processed_platform_update"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    update_id: Mapped[str] = mapped_column(String(200))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
