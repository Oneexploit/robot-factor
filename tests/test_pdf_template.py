from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from robot_factor.config import Settings
from robot_factor.invoice_service import InvoiceService
from robot_factor.models import CompanyProfile, Customer, Invoice, InvoiceItem
from robot_factor.pdf_service import PdfService


def test_renders_rtl_invoice_html(tmp_path) -> None:
    settings = Settings(INVOICE_STORAGE_DIR=tmp_path)
    renderer = PdfService(settings, InvoiceService())
    customer = Customer(display_name="مشتری نمونه", phone="09120000000")
    invoice = Invoice(
        number="INV-000001",
        invoice_type="invoice",
        status="final",
        created_by_admin_id=1,
        created_platform="telegram",
        issue_at=datetime.now(UTC),
        customer=customer,
        subtotal=1000,
        grand_total=1000,
    )
    invoice.items = [
        InvoiceItem(
            position=1,
            product_name="زغال لیمو",
            quantity=Decimal("1"),
            unit="کارتن",
            unit_price=1000,
            gross_amount=1000,
            taxable_amount=1000,
            total_amount=1000,
        )
    ]
    company = CompanyProfile(id=1, brand_name="زغال نمونه")

    document = renderer.render_html(invoice, company)

    assert 'dir="rtl"' in document
    assert "زغال لیمو" in document
    assert "INV-۰۰۰۰۰۱" in document
