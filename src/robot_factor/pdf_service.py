from __future__ import annotations

import base64
import mimetypes
import os
from datetime import datetime
from pathlib import Path

import jdatetime
from jinja2 import Environment, PackageLoader, select_autoescape
from playwright.async_api import async_playwright
from sqlalchemy.ext.asyncio import AsyncSession

from robot_factor.config import Settings
from robot_factor.invoice_service import InvoiceService
from robot_factor.models import CompanyProfile, Invoice, PdfStatus

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def to_fa(value: object) -> str:
    return str(value).translate(FA_DIGITS)


def format_money(value: int | None) -> str:
    return f"{value or 0:,}".translate(FA_DIGITS)


def format_quantity(value: object) -> str:
    text = f"{value:f}".rstrip("0").rstrip(".")
    return text.translate(FA_DIGITS)


def jalali_date(value: datetime | None) -> str:
    if value is None:
        return "—"
    local = jdatetime.datetime.fromgregorian(datetime=value)
    return local.strftime("%Y/%m/%d").translate(FA_DIGITS)


class PdfService:
    def __init__(self, settings: Settings, invoice_service: InvoiceService) -> None:
        self.settings = settings
        self.invoice_service = invoice_service
        self.environment = Environment(
            loader=PackageLoader("robot_factor", "templates"),
            autoescape=select_autoescape(["html", "xml"]),
            enable_async=False,
        )
        self.environment.filters.update(
            money=format_money,
            qty=format_quantity,
            fa=to_fa,
            jalali=jalali_date,
        )

    async def render_invoice(self, session: AsyncSession, invoice_id: int) -> Path:
        invoice = await self.invoice_service.get_invoice(session, invoice_id)
        company = await session.get(CompanyProfile, 1)
        if company is None:
            raise RuntimeError("company profile is missing")
        if not invoice.number:
            raise ValueError("draft invoices cannot be rendered")

        output_dir = self.settings.invoice_storage_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_number = "".join(
            character for character in invoice.number if character.isalnum() or character in "-_"
        )
        destination = output_dir / f"{safe_number}.pdf"
        temporary = destination.with_suffix(".tmp.pdf")

        try:
            document = self.render_html(invoice, company)
            await self._html_to_pdf(document, temporary)
            os.replace(temporary, destination)
            invoice.pdf_path = str(destination)
            invoice.pdf_status = PdfStatus.READY.value
            invoice.pdf_error = None
            await session.commit()
            return destination
        except Exception as error:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
            invoice.pdf_status = PdfStatus.FAILED.value
            invoice.pdf_error = str(error)[:2000]
            await session.commit()
            raise

    def render_html(self, invoice: Invoice, company: CompanyProfile) -> str:
        template = self.environment.get_template("invoice.html")
        logo_uri = self._asset_uri(company.logo_path)
        stamp_uri = self._asset_uri(company.stamp_path)
        return template.render(
            invoice=invoice,
            company=company,
            logo_uri=logo_uri,
            stamp_uri=stamp_uri,
            document_title=("پیش‌فاکتور" if invoice.invoice_type == "proforma" else "فاکتور فروش"),
        )

    async def _html_to_pdf(self, document: str, destination: Path) -> None:
        launch_options: dict[str, object] = {"headless": self.settings.pdf_headless}
        if self.settings.pdf_browser_executable_path:
            launch_options["executable_path"] = self.settings.pdf_browser_executable_path
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**launch_options)
            try:
                page = await browser.new_page()
                await page.set_content(document, wait_until="networkidle")
                await page.pdf(
                    path=str(destination),
                    format="A4",
                    print_background=True,
                    margin={"top": "10mm", "right": "10mm", "bottom": "10mm", "left": "10mm"},
                )
            finally:
                await browser.close()

    @staticmethod
    def _asset_uri(raw_path: str | None) -> str | None:
        if not raw_path:
            return None
        path = Path(raw_path).resolve()
        if not path.is_file():
            return None
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"
