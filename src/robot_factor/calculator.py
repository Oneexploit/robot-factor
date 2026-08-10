from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class LineInput:
    quantity: Decimal
    unit_price: int
    item_discount: int = 0
    vat_rate: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class LineTotals:
    gross_amount: int
    item_discount: int
    allocated_invoice_discount: int
    taxable_amount: int
    tax_amount: int
    total_amount: int


@dataclass(frozen=True, slots=True)
class InvoiceTotals:
    lines: tuple[LineTotals, ...]
    subtotal: int
    item_discount_total: int
    invoice_discount: int
    shipping_cost: int
    tax_total: int
    grand_total: int


def round_money(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def validate_line(line: LineInput) -> None:
    if line.quantity <= ZERO:
        raise ValueError("quantity must be greater than zero")
    if line.unit_price < 0:
        raise ValueError("unit price cannot be negative")
    gross = round_money(line.quantity * Decimal(line.unit_price))
    if line.item_discount < 0 or line.item_discount > gross:
        raise ValueError("item discount must be between zero and gross amount")
    if line.vat_rate < ZERO or line.vat_rate > Decimal("100"):
        raise ValueError("VAT rate must be between zero and 100")


def _allocate_proportionally(total: int, weights: list[int]) -> list[int]:
    if total == 0:
        return [0] * len(weights)
    weight_sum = sum(weights)
    if weight_sum <= 0 or total > weight_sum:
        raise ValueError("invoice discount exceeds discountable amount")

    exact = [Decimal(total) * Decimal(weight) / Decimal(weight_sum) for weight in weights]
    allocated = [int(value.quantize(Decimal("1"), rounding=ROUND_DOWN)) for value in exact]
    remainder = total - sum(allocated)
    order = sorted(
        range(len(weights)),
        key=lambda index: (exact[index] - Decimal(allocated[index]), weights[index], -index),
        reverse=True,
    )
    for index in order[:remainder]:
        allocated[index] += 1
    return allocated


def calculate_invoice(
    lines: list[LineInput] | tuple[LineInput, ...],
    *,
    invoice_discount: int = 0,
    shipping_cost: int = 0,
) -> InvoiceTotals:
    if not lines:
        raise ValueError("an invoice must contain at least one item")
    if invoice_discount < 0:
        raise ValueError("invoice discount cannot be negative")
    if shipping_cost < 0:
        raise ValueError("shipping cost cannot be negative")

    gross_amounts: list[int] = []
    net_weights: list[int] = []
    for line in lines:
        validate_line(line)
        gross = round_money(line.quantity * Decimal(line.unit_price))
        gross_amounts.append(gross)
        net_weights.append(gross - line.item_discount)

    allocated_discounts = _allocate_proportionally(invoice_discount, net_weights)
    calculated_lines: list[LineTotals] = []
    for line, gross, net, allocated_discount in zip(
        lines, gross_amounts, net_weights, allocated_discounts, strict=True
    ):
        taxable = net - allocated_discount
        tax = round_money(Decimal(taxable) * line.vat_rate / Decimal("100"))
        calculated_lines.append(
            LineTotals(
                gross_amount=gross,
                item_discount=line.item_discount,
                allocated_invoice_discount=allocated_discount,
                taxable_amount=taxable,
                tax_amount=tax,
                total_amount=taxable + tax,
            )
        )

    subtotal = sum(gross_amounts)
    item_discount_total = sum(line.item_discount for line in lines)
    tax_total = sum(line.tax_amount for line in calculated_lines)
    grand_total = subtotal - item_discount_total - invoice_discount + shipping_cost + tax_total
    return InvoiceTotals(
        lines=tuple(calculated_lines),
        subtotal=subtotal,
        item_discount_total=item_discount_total,
        invoice_discount=invoice_discount,
        shipping_cost=shipping_cost,
        tax_total=tax_total,
        grand_total=grand_total,
    )
