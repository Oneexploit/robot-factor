from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from robot_factor.config import Settings
from robot_factor.invoice_service import InvoiceService
from robot_factor.models import (
    AdminUser,
    CompanyProfile,
    ConversationSession,
    Invoice,
    InvoiceStatus,
    InvoiceType,
    ProcessedUpdate,
    Product,
)
from robot_factor.transport import Button, IncomingEvent, OutboundMessage

ASCII_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


class State:
    IDLE = "idle"
    CUSTOMER_NAME = "customer_name"
    CUSTOMER_PHONE = "customer_phone"
    ITEM_NAME = "item_name"
    ITEM_QUANTITY = "item_quantity"
    ITEM_UNIT = "item_unit"
    ITEM_PRICE = "item_price"
    ITEM_DISCOUNT = "item_discount"
    ITEM_VAT = "item_vat"
    ITEMS_REVIEW = "items_review"
    INVOICE_DISCOUNT = "invoice_discount"
    SHIPPING = "shipping"
    PAID = "paid"
    NOTES = "notes"
    CONFIRM = "confirm"


def fa(value: object) -> str:
    return str(value).translate(FA_DIGITS)


def money(value: int) -> str:
    return f"{value:,}".translate(FA_DIGITS)


def parse_decimal(text: str) -> Decimal:
    normalized = (
        text.translate(ASCII_DIGITS).replace(",", "").replace("٬", "").replace("٫", ".").strip()
    )
    try:
        value = Decimal(normalized)
    except InvalidOperation as error:
        raise ValueError("عدد نامعتبر است") from error
    if not value.is_finite():
        raise ValueError("عدد نامعتبر است")
    return value


def parse_money(text: str) -> int:
    value = parse_decimal(text)
    if value != value.to_integral_value() or value < 0:
        raise ValueError("مبلغ باید یک عدد صحیح و غیرمنفی باشد")
    return int(value)


def normalize_phone(text: str) -> str | None:
    normalized = text.translate(ASCII_DIGITS).strip()
    if normalized in {"-", "ندارد", "بدون شماره"}:
        return None
    keep = "".join(character for character in normalized if character.isdigit() or character == "+")
    if len(keep.replace("+", "")) < 7:
        raise ValueError("شماره تماس کوتاه یا نامعتبر است")
    return keep


class ConversationService:
    def __init__(self, settings: Settings, invoice_service: InvoiceService) -> None:
        self.settings = settings
        self.invoices = invoice_service

    async def handle(self, session: AsyncSession, event: IncomingEvent) -> list[OutboundMessage]:
        if await self._already_processed(session, event):
            return []

        admin = await session.scalar(
            select(AdminUser).where(
                AdminUser.platform == event.platform,
                AdminUser.external_user_id == event.user_id,
                AdminUser.is_active.is_(True),
            )
        )
        if admin is None:
            return [
                OutboundMessage(
                    "دسترسی این حساب فعال نیست. این شناسه را در تنظیمات مدیران ثبت کنید:\n"
                    f"{event.platform}:{event.user_id}"
                )
            ]

        conversation = await self._get_conversation(session, event)
        text = event.text.strip()
        command = (event.callback_data or text).strip()

        if text in {"/cancel", "لغو"} or command == "cancel":
            return await self._cancel(session, conversation, admin)

        if text in {"/start", "/menu", "منو"}:
            if conversation.state != State.IDLE:
                return [
                    OutboundMessage(
                        "یک پیش‌نویس فعال دارید. مرحلهٔ جاری را ادامه دهید یا آن را لغو کنید.",
                        buttons=((Button("لغو پیش‌نویس", "cancel"),),),
                    ),
                    self._prompt_for_state(conversation.state),
                ]
            return [await self._main_menu(session)]

        if command in {"new:invoice", "new:proforma"}:
            if conversation.state != State.IDLE:
                return [
                    OutboundMessage(
                        "ابتدا پیش‌نویس فعلی را تکمیل یا لغو کنید.",
                        buttons=((Button("لغو پیش‌نویس", "cancel"),),),
                    )
                ]
            invoice_type = (
                InvoiceType.PROFORMA.value
                if command.endswith("proforma")
                else InvoiceType.INVOICE.value
            )
            invoice = await self.invoices.create_draft(
                session, admin=admin, platform=event.platform, invoice_type=invoice_type
            )
            self._set_state(conversation, State.CUSTOMER_NAME, {"invoice_id": invoice.id})
            return [OutboundMessage("نام مشتری یا نام شرکت خریدار را وارد کنید:")]

        if conversation.state == State.IDLE:
            if command == "list:invoices":
                return [await self._list_invoices(session)]
            if command.startswith("pdf:"):
                invoice_id = int(command.split(":", 1)[1])
                invoice = await self.invoices.get_invoice(session, invoice_id)
                if invoice.status not in {
                    InvoiceStatus.FINAL.value,
                    InvoiceStatus.PAID.value,
                }:
                    raise ValueError("این سند هنوز نهایی نشده است")
                return [
                    OutboundMessage(
                        text=f"فایل PDF شماره {fa(invoice.number)}",
                        document_invoice_id=invoice.id,
                    )
                ]
            if command == "list:products":
                return [await self._list_products(session)]
            if command == "settings":
                return [await self._show_settings(session)]
            return [await self._main_menu(session)]

        try:
            return await self._handle_state(session, event, conversation, admin)
        except ValueError as error:
            return [OutboundMessage(f"ورودی معتبر نیست: {error}\nلطفاً دوباره وارد کنید.")]
        except LookupError:
            self._set_state(conversation, State.IDLE, {})
            return [
                OutboundMessage("پیش‌نویس پیدا نشد یا منقضی شده است."),
                await self._main_menu(session),
            ]

    async def _handle_state(
        self,
        session: AsyncSession,
        event: IncomingEvent,
        conversation: ConversationSession,
        admin: AdminUser,
    ) -> list[OutboundMessage]:
        text = event.text.strip()
        command = (event.callback_data or text).strip()
        payload = dict(conversation.payload)
        invoice = await self.invoices.get_invoice(session, int(payload["invoice_id"]))
        if invoice.status != InvoiceStatus.DRAFT.value:
            self._set_state(conversation, State.IDLE, {})
            return [
                OutboundMessage("این سند قبلاً نهایی یا بسته شده است."),
                await self._main_menu(session),
            ]

        if conversation.state == State.CUSTOMER_NAME:
            if len(text) < 2:
                raise ValueError("نام مشتری باید حداقل دو حرف داشته باشد")
            payload["customer_name"] = text[:250]
            self._set_state(conversation, State.CUSTOMER_PHONE, payload)
            return [OutboundMessage("شماره تماس مشتری را وارد کنید؛ اگر ندارید «-» بفرستید:")]

        if conversation.state == State.CUSTOMER_PHONE:
            phone = normalize_phone(text)
            await self.invoices.attach_customer(
                session,
                invoice=invoice,
                admin=admin,
                display_name=str(payload["customer_name"]),
                phone=phone,
            )
            company = await session.get(CompanyProfile, 1)
            payload["default_vat"] = str(company.default_vat_rate if company else 0)
            self._set_state(conversation, State.ITEM_NAME, payload)
            return [await self._product_prompt(session)]

        if conversation.state == State.ITEM_NAME:
            item: dict[str, object] = {}
            if command.startswith("product:"):
                product_id = int(command.split(":", 1)[1])
                product = await session.get(Product, product_id)
                if product is None or not product.is_active:
                    raise ValueError("این کالا دیگر فعال نیست")
                item = {
                    "product_id": product.id,
                    "name": product.name,
                    "unit": product.unit,
                    "price": product.default_unit_price,
                    "vat": str(product.vat_rate),
                }
            elif command == "product:manual":
                return [OutboundMessage("نام کالا را تایپ کنید:")]
            else:
                if len(text) < 2:
                    raise ValueError("نام کالا باید حداقل دو حرف داشته باشد")
                item = {"name": text[:250], "vat": str(payload.get("default_vat", "0"))}
            payload["item"] = item
            self._set_state(conversation, State.ITEM_QUANTITY, payload)
            return [OutboundMessage("مقدار/تعداد را وارد کنید؛ مثال: 10 یا 7.5")]

        if conversation.state == State.ITEM_QUANTITY:
            quantity = parse_decimal(text)
            if quantity <= 0 or quantity > Decimal("1000000000"):
                raise ValueError("مقدار باید بزرگ‌تر از صفر باشد")
            item = dict(payload.get("item") or {})
            item["quantity"] = str(quantity)
            payload["item"] = item
            if item.get("unit"):
                self._set_state(conversation, State.ITEM_PRICE, payload)
                default_price = money(int(item.get("price") or 0))
                return [
                    OutboundMessage(
                        f"قیمت واحد را وارد کنید؛ برای قیمت پیش‌فرض {default_price}، «-» بفرستید:"
                    )
                ]
            self._set_state(conversation, State.ITEM_UNIT, payload)
            return [OutboundMessage("واحد را وارد کنید؛ مثال: کیلوگرم، کارتن، کیسه یا عدد")]

        if conversation.state == State.ITEM_UNIT:
            if not 1 <= len(text) <= 32:
                raise ValueError("واحد کالا نامعتبر است")
            item = dict(payload["item"])
            item["unit"] = text
            payload["item"] = item
            self._set_state(conversation, State.ITEM_PRICE, payload)
            return [OutboundMessage("قیمت هر واحد را بدون جداکننده یا با ویرگول وارد کنید:")]

        if conversation.state == State.ITEM_PRICE:
            item = dict(payload["item"])
            if text == "-" and "price" in item:
                price = int(item["price"])
            else:
                price = parse_money(text)
            item["price"] = price
            payload["item"] = item
            self._set_state(conversation, State.ITEM_DISCOUNT, payload)
            return [OutboundMessage("تخفیف همین ردیف را وارد کنید؛ برای بدون تخفیف «0» بفرستید:")]

        if conversation.state == State.ITEM_DISCOUNT:
            item = dict(payload["item"])
            item["discount"] = parse_money(text)
            payload["item"] = item
            self._set_state(conversation, State.ITEM_VAT, payload)
            default_vat = item.get("vat")
            suffix = (
                f"؛ مقدار پیش‌فرض {fa(default_vat)}٪ است و می‌توانید «-» بفرستید"
                if default_vat is not None
                else ""
            )
            return [OutboundMessage(f"درصد مالیات این ردیف را وارد کنید؛ مثلاً 10 یا 0{suffix}:")]

        if conversation.state == State.ITEM_VAT:
            item = dict(payload["item"])
            vat = Decimal(str(item.get("vat", "0"))) if text == "-" else parse_decimal(text)
            if vat < 0 or vat > 100:
                raise ValueError("درصد مالیات باید بین صفر و صد باشد")
            await self.invoices.add_item(
                session,
                invoice=invoice,
                product_name=str(item["name"]),
                quantity=Decimal(str(item["quantity"])),
                unit=str(item["unit"]),
                unit_price=int(item["price"]),
                item_discount=int(item["discount"]),
                vat_rate=vat,
                product_id=int(item["product_id"]) if item.get("product_id") else None,
            )
            payload.pop("item", None)
            self._set_state(conversation, State.ITEMS_REVIEW, payload)
            return [self._items_review(invoice), self._items_actions()]

        if conversation.state == State.ITEMS_REVIEW:
            if command == "item:add":
                self._set_state(conversation, State.ITEM_NAME, payload)
                return [await self._product_prompt(session)]
            if command == "item:remove_last":
                removed = await self.invoices.remove_last_item(session, invoice)
                if not removed:
                    return [OutboundMessage("ردیفی برای حذف وجود ندارد."), self._items_actions()]
                if not invoice.items:
                    self._set_state(conversation, State.ITEM_NAME, payload)
                    return [
                        OutboundMessage("تنها ردیف حذف شد."),
                        await self._product_prompt(session),
                    ]
                return [self._items_review(invoice), self._items_actions()]
            if command == "adjustments":
                self._set_state(conversation, State.INVOICE_DISCOUNT, payload)
                return [
                    OutboundMessage("تخفیف کلی فاکتور را وارد کنید؛ برای بدون تخفیف «0» بفرستید:")
                ]
            return [OutboundMessage("یکی از دکمه‌های زیر را انتخاب کنید."), self._items_actions()]

        if conversation.state == State.INVOICE_DISCOUNT:
            discount = parse_money(text)
            discountable = sum(item.gross_amount - item.item_discount for item in invoice.items)
            if discount > discountable:
                raise ValueError("تخفیف کلی از مبلغ قابل تخفیف بیشتر است")
            payload["invoice_discount"] = discount
            self._set_state(conversation, State.SHIPPING, payload)
            return [OutboundMessage("هزینه حمل را وارد کنید؛ برای بدون هزینه «0» بفرستید:")]

        if conversation.state == State.SHIPPING:
            payload["shipping_cost"] = parse_money(text)
            self._set_state(conversation, State.PAID, payload)
            return [
                OutboundMessage("مبلغی که تاکنون پرداخت شده را وارد کنید؛ برای هیچ «0» بفرستید:")
            ]

        if conversation.state == State.PAID:
            paid_amount = parse_money(text)
            self.invoices.set_adjustments(
                invoice,
                invoice_discount=int(payload.get("invoice_discount", 0)),
                shipping_cost=int(payload.get("shipping_cost", 0)),
                paid_amount=paid_amount,
                notes=invoice.notes,
            )
            payload["paid_amount"] = paid_amount
            self._set_state(conversation, State.NOTES, payload)
            return [OutboundMessage("توضیحات یا شرایط فروش را بنویسید؛ اگر ندارید «-» بفرستید:")]

        if conversation.state == State.NOTES:
            notes = None if text == "-" else text[:2000]
            self.invoices.set_adjustments(
                invoice,
                invoice_discount=int(payload.get("invoice_discount", 0)),
                shipping_cost=int(payload.get("shipping_cost", 0)),
                paid_amount=int(payload.get("paid_amount", 0)),
                notes=notes,
            )
            self._set_state(conversation, State.CONFIRM, payload)
            return [self._invoice_preview(invoice), self._confirm_actions()]

        if conversation.state == State.CONFIRM:
            if command == "item:add":
                self._set_state(conversation, State.ITEM_NAME, payload)
                return [await self._product_prompt(session)]
            if command == "edit:adjustments":
                self._set_state(conversation, State.INVOICE_DISCOUNT, payload)
                return [OutboundMessage("تخفیف کلی جدید را وارد کنید:")]
            if command == "finalize":
                await self.invoices.finalize(session, invoice=invoice, admin=admin)
                self._set_state(conversation, State.IDLE, {})
                document_type = "پیش‌فاکتور" if invoice.invoice_type == "proforma" else "فاکتور"
                return [
                    OutboundMessage(
                        f"{document_type} شماره {fa(invoice.number)} با موفقیت نهایی شد."
                    ),
                    OutboundMessage(
                        text=f"فایل PDF {document_type} {fa(invoice.number)}",
                        document_invoice_id=invoice.id,
                    ),
                    await self._main_menu(session),
                ]
            return [
                OutboundMessage("برای صدور PDF باید دکمهٔ تأیید نهایی را بزنید."),
                self._confirm_actions(),
            ]

        self._set_state(conversation, State.IDLE, {})
        return [await self._main_menu(session)]

    async def _get_conversation(
        self, session: AsyncSession, event: IncomingEvent
    ) -> ConversationSession:
        conversation = await session.scalar(
            select(ConversationSession).where(
                ConversationSession.platform == event.platform,
                ConversationSession.chat_id == event.chat_id,
                ConversationSession.external_user_id == event.user_id,
            )
        )
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=self.settings.session_ttl_minutes)
        if conversation is None:
            conversation = ConversationSession(
                platform=event.platform,
                chat_id=event.chat_id,
                external_user_id=event.user_id,
                state=State.IDLE,
                payload={},
                expires_at=expires_at,
            )
            session.add(conversation)
            await session.flush()
            return conversation

        current_expiry = conversation.expires_at
        if current_expiry.tzinfo is None:
            current_expiry = current_expiry.replace(tzinfo=UTC)
        if current_expiry <= now:
            conversation.state = State.IDLE
            conversation.payload = {}
        conversation.expires_at = expires_at
        return conversation

    async def _already_processed(self, session: AsyncSession, event: IncomingEvent) -> bool:
        exists = await session.scalar(
            select(ProcessedUpdate.id).where(
                ProcessedUpdate.platform == event.platform,
                ProcessedUpdate.update_id == event.update_id,
            )
        )
        if exists is not None:
            return True
        try:
            async with session.begin_nested():
                session.add(
                    ProcessedUpdate(platform=event.platform, update_id=event.update_id[:200])
                )
                await session.flush()
        except IntegrityError:
            return True
        return False

    async def _cancel(
        self,
        session: AsyncSession,
        conversation: ConversationSession,
        admin: AdminUser,
    ) -> list[OutboundMessage]:
        invoice_id = conversation.payload.get("invoice_id")
        if invoice_id:
            try:
                invoice = await self.invoices.get_invoice(session, int(invoice_id))
                if invoice.status == InvoiceStatus.DRAFT.value:
                    await self.invoices.cancel_draft(session, invoice=invoice, admin=admin)
            except LookupError:
                pass
        self._set_state(conversation, State.IDLE, {})
        return [OutboundMessage("پیش‌نویس لغو شد."), await self._main_menu(session)]

    async def _main_menu(self, session: AsyncSession) -> OutboundMessage:
        company = await session.get(CompanyProfile, 1)
        brand = company.brand_name if company else "سامانه فاکتور"
        return OutboundMessage(
            f"{brand}\nعملیات موردنظر را انتخاب کنید:",
            buttons=(
                (Button("فاکتور جدید", "new:invoice"), Button("پیش‌فاکتور", "new:proforma")),
                (Button("فاکتورهای اخیر", "list:invoices"), Button("کالاها", "list:products")),
                (Button("تنظیمات فروشگاه", "settings"),),
            ),
        )

    async def _product_prompt(self, session: AsyncSession) -> OutboundMessage:
        products = list(
            (
                await session.scalars(
                    select(Product)
                    .where(Product.is_active.is_(True))
                    .order_by(Product.name)
                    .limit(8)
                )
            ).all()
        )
        buttons: list[tuple[Button, ...]] = []
        for index in range(0, len(products), 2):
            row = tuple(
                Button(product.name[:32], f"product:{product.id}")
                for product in products[index : index + 2]
            )
            buttons.append(row)
        buttons.append((Button("ورود کالای جدید/دستی", "product:manual"),))
        return OutboundMessage(
            "کالا را انتخاب کنید یا نام کالای جدید را مستقیم تایپ کنید:",
            buttons=tuple(buttons),
        )

    async def _list_invoices(self, session: AsyncSession) -> OutboundMessage:
        invoices = list(
            (
                await session.scalars(
                    select(Invoice)
                    .where(
                        Invoice.status.in_([InvoiceStatus.FINAL.value, InvoiceStatus.PAID.value])
                    )
                    .order_by(Invoice.finalized_at.desc())
                    .limit(10)
                )
            ).all()
        )
        if not invoices:
            return OutboundMessage("هنوز فاکتور نهایی‌شده‌ای وجود ندارد.")
        company = await session.get(CompanyProfile, 1)
        unit = company.money_unit if company else "تومان"
        lines = ["آخرین فاکتورها:"]
        for invoice in invoices:
            lines.append(
                f"• {fa(invoice.number)} — {money(invoice.grand_total)} {unit} — "
                f"{'پرداخت‌شده' if invoice.status == 'paid' else 'نهایی'}"
            )
        buttons = tuple(
            (Button(f"PDF {fa(invoice.number)}", f"pdf:{invoice.id}"),) for invoice in invoices[:5]
        )
        return OutboundMessage("\n".join(lines), buttons=buttons)

    async def _list_products(self, session: AsyncSession) -> OutboundMessage:
        products = list(
            (
                await session.scalars(
                    select(Product)
                    .where(Product.is_active.is_(True))
                    .order_by(Product.name)
                    .limit(25)
                )
            ).all()
        )
        if not products:
            return OutboundMessage(
                "هنوز کالایی ثبت نشده است. کالا را هنگام صدور فاکتور دستی وارد کنید "
                "یا از API مدیریت بسازید."
            )
        company = await session.get(CompanyProfile, 1)
        unit = company.money_unit if company else "تومان"
        lines = ["کالاهای فعال:"]
        lines.extend(
            f"• {product.name} — {money(product.default_unit_price)} {unit}/{product.unit}"
            for product in products
        )
        return OutboundMessage("\n".join(lines))

    async def _show_settings(self, session: AsyncSession) -> OutboundMessage:
        company = await session.get(CompanyProfile, 1)
        if company is None:
            return OutboundMessage("پروفایل فروشگاه هنوز ساخته نشده است.")
        return OutboundMessage(
            "تنظیمات فعال:\n"
            f"• برند: {company.brand_name}\n"
            f"• واحد پول: {company.money_unit}\n"
            f"• پیشوند فاکتور: {company.invoice_prefix}\n"
            f"• مالیات پیش‌فرض: {fa(company.default_vat_rate)}٪\n\n"
            "ویرایش اطلاعات هویتی و بانکی از API مدیریت امن انجام می‌شود."
        )

    @staticmethod
    def _items_review(invoice: Invoice) -> OutboundMessage:
        lines = ["ردیف‌های فعلی:"]
        for item in invoice.items:
            lines.append(
                f"{fa(item.position)}. {item.product_name} — {fa(item.quantity)} {item.unit} — "
                f"{money(item.total_amount)}"
            )
        lines.append(f"جمع فعلی: {money(invoice.grand_total)}")
        return OutboundMessage("\n".join(lines))

    @staticmethod
    def _items_actions() -> OutboundMessage:
        return OutboundMessage(
            "مرحله بعد:",
            buttons=(
                (Button("افزودن کالا", "item:add"), Button("حذف ردیف آخر", "item:remove_last")),
                (Button("هزینه‌ها و تأیید", "adjustments"),),
                (Button("لغو", "cancel"),),
            ),
        )

    @staticmethod
    def _invoice_preview(invoice: Invoice) -> OutboundMessage:
        customer = invoice.customer.display_name if invoice.customer else "—"
        lines = [
            "پیش‌نمایش نهایی",
            f"مشتری: {customer}",
            f"تعداد ردیف: {fa(len(invoice.items))}",
            f"جمع کالاها: {money(invoice.subtotal)}",
            f"تخفیف ردیف‌ها: {money(invoice.item_discount_total)}",
            f"تخفیف فاکتور: {money(invoice.invoice_discount)}",
            f"مالیات: {money(invoice.tax_total)}",
            f"حمل: {money(invoice.shipping_cost)}",
            f"مبلغ نهایی: {money(invoice.grand_total)}",
            f"پرداخت‌شده: {money(invoice.paid_amount)}",
            f"مانده: {money(invoice.balance_due)}",
        ]
        return OutboundMessage("\n".join(lines))

    @staticmethod
    def _confirm_actions() -> OutboundMessage:
        return OutboundMessage(
            "پس از تأیید نهایی، شماره صادر می‌شود و مبالغ قابل ویرایش نیستند.",
            buttons=(
                (Button("تأیید و ساخت PDF", "finalize"),),
                (Button("ویرایش هزینه‌ها", "edit:adjustments"), Button("افزودن کالا", "item:add")),
                (Button("لغو", "cancel"),),
            ),
        )

    @staticmethod
    def _prompt_for_state(state: str) -> OutboundMessage:
        prompts = {
            State.CUSTOMER_NAME: "نام مشتری را وارد کنید.",
            State.CUSTOMER_PHONE: "شماره تماس مشتری یا «-» را وارد کنید.",
            State.ITEM_NAME: "نام کالا را وارد کنید.",
            State.ITEM_QUANTITY: "مقدار کالا را وارد کنید.",
            State.ITEM_UNIT: "واحد کالا را وارد کنید.",
            State.ITEM_PRICE: "قیمت واحد را وارد کنید.",
            State.ITEM_DISCOUNT: "تخفیف ردیف را وارد کنید.",
            State.ITEM_VAT: "درصد مالیات را وارد کنید.",
            State.INVOICE_DISCOUNT: "تخفیف کلی را وارد کنید.",
            State.SHIPPING: "هزینه حمل را وارد کنید.",
            State.PAID: "مبلغ پرداخت‌شده را وارد کنید.",
            State.NOTES: "توضیحات یا «-» را وارد کنید.",
        }
        return OutboundMessage(prompts.get(state, "مرحلهٔ فعلی را از دکمه‌های قبلی ادامه دهید."))

    @staticmethod
    def _set_state(
        conversation: ConversationSession, state: str, payload: dict[str, object]
    ) -> None:
        conversation.state = state
        conversation.payload = dict(payload)
