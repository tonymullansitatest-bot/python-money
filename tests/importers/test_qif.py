from pathlib import Path

from finance_manager.infrastructure.qif import parse_qif, parse_qif_date


def test_parse_qif(tmp_path: Path):
    qif = tmp_path / "sample.qif"
    qif.write_text(
        "!Type:Bank\nD01/15/2026\nT-12.34\nPExample Shop\nMWeekly shop\nLFood:Groceries\n^\n"
        "D01/20/2026\nT2500.00\nPSalary\n^\n",
        encoding="utf-8"
    )
    records = parse_qif(qif)
    assert len(records) == 2
    assert records[0]["payee"] == "Example Shop"
    assert str(records[0]["amount"]) == "-12.34"
    assert records[0]["category"] == "Food:Groceries"
    assert records[1]["date"].isoformat() == "2026-01-20"


def test_date_formats():
    assert parse_qif_date("15/01/2026").isoformat() == "2026-01-15"


def test_apostrophe_date_is_day_first():
    assert parse_qif_date("11/01'2012").isoformat() == "2012-01-11"
    assert parse_qif_date("26/12'2011").isoformat() == "2011-12-26"


def test_import_books_account_categories_as_transfers(session):
    from datetime import date

    from finance_manager.application.services import (
        AccountService, ImportService, ReportService
    )

    account = AccountService(session).create_account("Card")
    records = [
        {"date": date(2026, 1, 5), "amount": "-50.00", "category": "[Current]"},
        {"date": date(2026, 1, 6), "amount": "-3.00", "payee": "Cafe", "category": "Food"},
    ]
    result = ImportService(session).commit_qif("x.qif", account.id, records)
    assert result["imported"] == 2
    assert AccountService(session).balance(account.id) == -5300
    totals = ReportService(session).income_expense(date(2026, 1, 1), date(2026, 1, 31))
    assert totals["EUR"]["expenses_minor"] == 300
    breakdown = ReportService(session).category_breakdown(
        date(2026, 1, 1), date(2026, 1, 31)
    )
    assert [r["category"] for r in breakdown] == ["Food"]
