"""Parse common bank transaction records from Quicken Interchange Format (QIF)."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


_DATE_FORMATS = (
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%m-%d-%Y",
    "%d-%m-%Y",
)
_CURRENCY_SYMBOLS = (",", "$", "£", "€")


def parse_qif_date(value: str):
    """Parse a date string using the supported QIF date formats."""
    value = value.strip()
    for date_format in _DATE_FORMATS:
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported QIF date: {value!r}")


def _parse_qif_amount(value: str) -> Decimal:
    """Parse a QIF amount after removing common formatting characters."""
    normalized = value
    for character in _CURRENCY_SYMBOLS:
        normalized = normalized.replace(character, "")
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid QIF amount: {value!r}") from exc


def parse_qif(path: str | Path) -> list[dict]:
    """Return transaction dictionaries parsed from a QIF file.

    Every record must contain a date and amount. Common payee, memo, category,
    reference, and cleared-status fields are included when present; unknown
    tags are ignored. The source file is not modified.
    """
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    records = []
    current = {}

    def finish():
        nonlocal current
        if not current:
            return
        if "date" not in current or "amount" not in current:
            raise ValueError(f"Incomplete QIF record: {current}")
        records.append(current)
        current = {}

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r\n")
        if not line:
            continue
        tag, value = line[0], line[1:].strip()
        if tag == "^":
            finish()
        elif tag == "D":
            current["date"] = parse_qif_date(value)
        elif tag == "T":
            current["amount"] = _parse_qif_amount(value)
        elif tag == "P":
            current["payee"] = value
        elif tag == "M":
            current["memo"] = value
        elif tag == "L":
            current["category"] = value
        elif tag == "N":
            current["reference"] = value
        elif tag == "C":
            current["cleared"] = value
        # Unknown tags are intentionally ignored.
    finish()
    return records
