from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    brand_name: str
    legal_name: str | None
    phone: str | None
    website: str | None
    address: str | None
    postal_code: str | None
    national_id: str | None
    registration_number: str | None
    economic_code: str | None
    card_number: str | None
    iban: str | None
    account_holder: str | None
    logo_path: str | None
    stamp_path: str | None
    footer_text: str | None
    money_unit: str
    default_vat_rate: Decimal
    invoice_prefix: str
    proforma_prefix: str
    next_invoice_sequence: int
    next_proforma_sequence: int


class CompanyUpdate(BaseModel):
    brand_name: str | None = Field(default=None, min_length=2, max_length=200)
    legal_name: str | None = Field(default=None, max_length=250)
    phone: str | None = Field(default=None, max_length=64)
    website: str | None = Field(default=None, max_length=250)
    address: str | None = Field(default=None, max_length=2000)
    postal_code: str | None = Field(default=None, max_length=32)
    national_id: str | None = Field(default=None, max_length=32)
    registration_number: str | None = Field(default=None, max_length=32)
    economic_code: str | None = Field(default=None, max_length=32)
    card_number: str | None = Field(default=None, max_length=32)
    iban: str | None = Field(default=None, max_length=34)
    account_holder: str | None = Field(default=None, max_length=200)
    logo_path: str | None = Field(default=None, max_length=500)
    stamp_path: str | None = Field(default=None, max_length=500)
    footer_text: str | None = Field(default=None, max_length=2000)
    money_unit: str | None = Field(default=None, pattern="^(تومان|ریال)$")
    default_vat_rate: Decimal | None = Field(default=None, ge=0, le=100)
    invoice_prefix: str | None = Field(default=None, min_length=1, max_length=32)
    proforma_prefix: str | None = Field(default=None, min_length=1, max_length=32)


class ProductCreate(BaseModel):
    sku: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=2, max_length=250)
    grade: str | None = Field(default=None, max_length=100)
    packaging: str | None = Field(default=None, max_length=100)
    unit: str = Field(default="کیلوگرم", min_length=1, max_length=32)
    weight_per_package: Decimal | None = Field(default=None, gt=0)
    default_unit_price: int = Field(default=0, ge=0)
    vat_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    is_active: bool = True


class ProductUpdate(BaseModel):
    sku: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, min_length=2, max_length=250)
    grade: str | None = Field(default=None, max_length=100)
    packaging: str | None = Field(default=None, max_length=100)
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    weight_per_package: Decimal | None = Field(default=None, gt=0)
    default_unit_price: int | None = Field(default=None, ge=0)
    vat_rate: Decimal | None = Field(default=None, ge=0, le=100)
    is_active: bool | None = None


class ProductRead(ProductCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    display_name: str
    contact_name: str | None
    phone: str | None
    national_id: str | None
    economic_code: str | None
    address: str | None
    postal_code: str | None
    notes: str | None
    created_at: datetime


class InvoiceItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    product_name: str
    description: str | None
    quantity: Decimal
    unit: str
    unit_price: int
    item_discount: int
    allocated_invoice_discount: int
    vat_rate: Decimal
    tax_amount: int
    total_amount: int


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str | None
    invoice_type: str
    status: str
    customer: CustomerRead | None
    issue_at: datetime | None
    valid_until: date | None
    subtotal: int
    item_discount_total: int
    invoice_discount: int
    shipping_cost: int
    tax_total: int
    grand_total: int
    paid_amount: int
    balance_due: int
    notes: str | None
    pdf_status: str
    items: list[InvoiceItemRead]
    created_at: datetime
