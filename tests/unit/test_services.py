from datetime import date
from decimal import Decimal

from finance_manager.application.services import (
    AccountService, ReportService, TransactionService, TransferService
)
from finance_manager.domain.enums import AccountType


def test_income_expense_and_balance(session):
    account = AccountService(session).create_account(
        "Everyday", AccountType.CURRENT.value, "100.00"
    )
    tx = TransactionService(session)
    tx.add_transaction(account.id, date(2026, 1, 2), "250.00", "Income", "Employer")
    tx.add_transaction(account.id, date(2026, 1, 3), "40.00", "Expense", "Shop")
    assert AccountService(session).balance(account.id) == 31000
    report = ReportService(session).income_expense(date(2026, 1, 1), date(2026, 1, 31))
    assert report == {
        "income_minor": 25000, "expenses_minor": 4000, "net_minor": 21000
    }


def test_transfer_is_balanced_and_not_income_expense(session):
    service = AccountService(session)
    a = service.create_account("Current")
    b = service.create_account("Savings", AccountType.SAVINGS.value)
    TransferService(session).create_transfer(a.id, b.id, "25.00", date(2026, 2, 1))
    assert service.balance(a.id) == -2500
    assert service.balance(b.id) == 2500
    report = ReportService(session).income_expense(date(2026, 1, 1), date(2026, 12, 31))
    assert report["income_minor"] == 0
    assert report["expenses_minor"] == 0
