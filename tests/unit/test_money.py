from decimal import Decimal

from finance_manager.domain.money import from_minor_units, to_minor_units


def test_money_round_trip():
    assert to_minor_units(Decimal("12.34")) == 1234
    assert from_minor_units(1234) == Decimal("12.34")


def test_money_rounds_half_up():
    assert to_minor_units("1.235") == 124
