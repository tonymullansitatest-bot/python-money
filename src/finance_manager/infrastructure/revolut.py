"""Parse Revolut account statement CSV exports."""

import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

REQUIRED_COLUMNS = (
    "Type", "Product", "Started Date", "Completed Date", "Description",
    "Amount", "Fee", "Currency", "State",
)
_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def _parse_datetime(value: str, column: str):
    value = (value or "").strip()
    for date_format in _DATE_FORMATS:
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            continue
    raise ValueError(f"Unsupported Revolut date in {column}: {value!r}")


def _parse_decimal(value: str, column: str) -> Decimal:
    try:
        return Decimal((value or "0").strip() or "0")
    except InvalidOperation as exc:
        raise ValueError(f"Invalid Revolut {column}: {value!r}") from exc


def parse_revolut_csv(path: str | Path) -> list[dict]:
    """Return one record per statement row, in file order.

    Each record has type, product, started, completed (None while pending),
    description, amount, fee, currency and state.
    """
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(
                "Not a Revolut statement; missing columns: " + ", ".join(missing)
            )
        records = []
        for row in reader:
            completed = (row["Completed Date"] or "").strip()
            records.append({
                "type": row["Type"].strip(),
                "product": row["Product"].strip(),
                "started": _parse_datetime(row["Started Date"], "Started Date"),
                "completed": (
                    _parse_datetime(completed, "Completed Date") if completed else None
                ),
                "description": (row["Description"] or "").strip(),
                "amount": _parse_decimal(row["Amount"], "Amount"),
                "fee": _parse_decimal(row["Fee"], "Fee"),
                "currency": row["Currency"].strip().upper(),
                "state": row["State"].strip().upper(),
            })
    return records
