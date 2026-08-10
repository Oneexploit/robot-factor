from decimal import Decimal

import pytest

from robot_factor.calculator import LineInput, calculate_invoice


def test_calculates_discount_shipping_and_mixed_vat_deterministically() -> None:
    totals = calculate_invoice(
        [
            LineInput(Decimal("2"), 100_000, item_discount=10_000, vat_rate=Decimal("10")),
            LineInput(Decimal("1"), 300_000, vat_rate=Decimal("0")),
        ],
        invoice_discount=49_000,
        shipping_cost=20_000,
    )

    assert totals.subtotal == 500_000
    assert totals.item_discount_total == 10_000
    assert sum(line.allocated_invoice_discount for line in totals.lines) == 49_000
    assert totals.lines[0].allocated_invoice_discount == 19_000
    assert totals.lines[0].tax_amount == 17_100
    assert totals.tax_total == 17_100
    assert totals.grand_total == 478_100


@pytest.mark.parametrize(
    ("discount", "shipping"),
    [(-1, 0), (0, -1), (101, 0)],
)
def test_rejects_invalid_invoice_values(discount: int, shipping: int) -> None:
    with pytest.raises(ValueError):
        calculate_invoice(
            [LineInput(Decimal("1"), 100)],
            invoice_discount=discount,
            shipping_cost=shipping,
        )


def test_rounds_money_half_up() -> None:
    totals = calculate_invoice([LineInput(Decimal("1.5"), 1, vat_rate=Decimal("10"))])
    assert totals.subtotal == 2
    assert totals.tax_total == 0
