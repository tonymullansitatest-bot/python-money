from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def to_minor_units(value: Decimal | str | int | float) -> int:
    """Convert a monetary value to integer cents without binary-float arithmetic."""
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid monetary amount: {value}") from exc
    return int(amount * 100)


def from_minor_units(value: int) -> Decimal:
    return (Decimal(value) / Decimal(100)).quantize(Decimal("0.01"))


def format_money(value: Decimal | int, currency: str = "EUR") -> str:
    amount = Decimal(value) if not isinstance(value, Decimal) else value
    return f"{currency} {amount:,.2f}"
