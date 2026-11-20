from datetime import date
from pathlib import Path

import pytest

from finance_manager.application.services import (
    AccountService, ImportService, ReportService
)
from finance_manager.infrastructure.revolut import parse_revolut_csv

HEADER = "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n"
ROWS = (
    "Card Payment,Current,2026-11-01 10:00:00,2026-11-02 08:00:00,Cafe,-5.00,0.00,EUR,COMPLETED,95.00\n"
    "Card Payment,Current,2026-11-01 11:00:00,2026-11-02 08:00:00,Cafe,-5.00,0.00,EUR,COMPLETED,90.00\n"
    "Topup,Current,2026-11-03 09:00:00,2026-11-03 09:00:01,Top-up,200.00,0.00,EUR,COMPLETED,290.00\n"
    "Transfer,Current,2026-11-04 09:00:00,2026-11-04 09:00:01,To Robo portfolio,-3.00,0.00,EUR,COMPLETED,287.00\n"
    "Card Payment,Current,2026-11-05 09:00:00,,Shop,-9.00,0.00,EUR,PENDING,287.00\n"
)


@pytest.fixture
def statement(tmp_path: Path):
    path = tmp_path / "statement.csv"
    path.write_text(HEADER + ROWS, encoding="utf-8-sig")
    return path


def test_parse_revolut_csv(statement):
    records = parse_revolut_csv(statement)
    assert len(records) == 5
    assert records[0]["started"].date() == date(2026, 11, 1)
    assert records[-1]["completed"] is None


def test_parse_rejects_other_csv(tmp_path):
    path = tmp_path / "other.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_revolut_csv(path)


def test_import_maps_types_skips_pending_and_is_repeatable(session, statement):
    account = AccountService(session).create_account("Revolut")
    records = parse_revolut_csv(statement)
    service = ImportService(session)
    result = service.commit_revolut("s.csv", account.id, records)
    assert (result["imported"], result["pending"], result["skipped"]) == (4, 1, 0)
    # Same-day identical purchases at different times are both kept.
    assert AccountService(session).balance(account.id) == 18700
    totals = ReportService(session).income_expense(date(2026, 11, 1), date(2026, 11, 30))
    assert totals["EUR"] == {
        "income_minor": 20000, "expenses_minor": 1000, "net_minor": 19000
    }
    again = service.commit_revolut("s.csv", account.id, records)
    assert (again["imported"], again["skipped"]) == (0, 4)


def test_import_rejects_currency_mismatch(session, statement):
    account = AccountService(session).create_account("Sterling", currency="GBP")
    with pytest.raises(ValueError):
        ImportService(session).commit_revolut(
            "s.csv", account.id, parse_revolut_csv(statement)
        )
