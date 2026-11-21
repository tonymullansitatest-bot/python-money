from datetime import date
from decimal import Decimal

import pytest

from finance_manager.application.services import (
    AccountService,
    CategoryService,
    ReportService,
    ScheduledTransactionService,
    TransactionService,
    TransferService,
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
        "EUR": {"income_minor": 25000, "expenses_minor": 4000, "net_minor": 21000}
    }


def test_transfer_is_balanced_and_not_income_expense(session):
    service = AccountService(session)
    a = service.create_account("Current")
    b = service.create_account("Savings", AccountType.SAVINGS.value)
    TransferService(session).create_transfer(a.id, b.id, "25.00", date(2026, 2, 1))
    assert service.balance(a.id) == -2500
    assert service.balance(b.id) == 2500
    report = ReportService(session).income_expense(date(2026, 1, 1), date(2026, 12, 31))
    assert report == {}


def test_update_and_delete_transaction(session):
    accounts = AccountService(session)
    a = accounts.create_account("A", opening_balance="0.00")
    b = accounts.create_account("B")
    service = TransactionService(session)
    tx = service.add_transaction(a.id, date(2026, 1, 2), "40.00", "Expense", "Shop")
    service.update_transaction(tx.id, b.id, date(2026, 1, 5), "60.00", "Income", "Employer")
    assert accounts.balance(a.id) == 0
    assert accounts.balance(b.id) == 6000
    with pytest.raises(ValueError):
        service.update_transaction(tx.id, b.id, date(2026, 1, 5), "0", "Income")
    assert service.delete_transaction(tx.id) == 1
    assert accounts.balance(b.id) == 0
    with pytest.raises(ValueError):
        service.delete_transaction(tx.id)


def test_transfer_cannot_be_edited_and_delete_removes_both_legs(session):
    accounts = AccountService(session)
    a = accounts.create_account("A")
    b = accounts.create_account("B")
    TransferService(session).create_transfer(a.id, b.id, "10.00", date(2026, 2, 1))
    service = TransactionService(session)
    leg = service.list_transactions(account_id=a.id)[0]
    with pytest.raises(ValueError):
        service.update_transaction(leg.id, a.id, date(2026, 2, 1), "5", "Expense")
    assert service.delete_transaction(leg.id) == 2
    assert accounts.balance(a.id) == 0
    assert accounts.balance(b.id) == 0


def test_update_and_delete_account(session):
    accounts = AccountService(session)
    a = accounts.create_account("A", currency="EUR")
    accounts.update_account(a.id, "Renamed", AccountType.SAVINGS.value, "50.00", "usd")
    assert (a.name, a.currency, accounts.balance(a.id)) == ("Renamed", "USD", 5000)
    TransactionService(session).add_transaction(a.id, date(2026, 1, 1), "5", "Expense")
    with pytest.raises(ValueError):
        accounts.update_account(a.id, "Renamed", AccountType.SAVINGS.value, "50", "EUR")
    with pytest.raises(ValueError):
        accounts.delete_account(a.id)
    empty = accounts.create_account("Empty")
    accounts.delete_account(empty.id)
    assert empty.id not in [x.id for x in accounts.list_accounts()]


def test_archived_account_hidden_and_blocks_new_activity(session):
    accounts = AccountService(session)
    a = accounts.create_account("A")
    b = accounts.create_account("B")
    TransactionService(session).add_transaction(a.id, date(2026, 1, 1), "5", "Expense")
    accounts.set_active(a.id, False)
    assert [x.id for x in accounts.list_accounts(active_only=True)] == [b.id]
    assert len(accounts.list_accounts()) == 2
    assert accounts.balance(a.id) == -500
    with pytest.raises(ValueError):
        TransactionService(session).add_transaction(a.id, date(2026, 1, 2), "1", "Expense")
    with pytest.raises(ValueError):
        TransferService(session).create_transfer(a.id, b.id, "1", date(2026, 1, 2))
    accounts.set_active(a.id, True)
    TransferService(session).create_transfer(a.id, b.id, "1", date(2026, 1, 2))


def test_cross_currency_transfer_converts_amount(session):
    service = AccountService(session)
    eur = service.create_account("Euro", currency="EUR")
    usd = service.create_account("Dollar", currency="USD")
    transfers = TransferService(session)
    transfers.create_transfer(eur.id, usd.id, "100.00", date(2026, 2, 1), "", "1.0855")
    assert service.balance(eur.id) == -10000
    assert service.balance(usd.id) == 10855
    with pytest.raises(ValueError):
        transfers.create_transfer(eur.id, usd.id, "10.00", date(2026, 2, 1))
    with pytest.raises(ValueError):
        transfers.create_transfer(eur.id, usd.id, "10.00", date(2026, 2, 1), "", "0")


def test_scheduled_transaction_posts_manually_and_advances_month_end(session):
    account = AccountService(session).create_account("Current")
    category = CategoryService(session).create_category("Utilities", "Expense")
    schedules = ScheduledTransactionService(session)
    schedule = schedules.create_schedule(
        "Electricity bill", account.id, "100.00", "Expense",
        date(2026, 1, 31), category.id, "Power company"
    )

    assert schedules.due_schedules(date(2026, 1, 30)) == []
    with pytest.raises(ValueError, match="not due"):
        schedules.post_due(schedule.id, date(2026, 1, 30))

    posted = schedules.post_due(schedule.id, date(2026, 1, 31))
    assert (posted.transaction_date, posted.signed_amount_minor) == (
        date(2026, 1, 31), -10000
    )
    assert posted.category_id == category.id
    assert schedule.next_due_date == date(2026, 2, 28)
    assert AccountService(session).balance(account.id) == -10000

    schedules.post_due(schedule.id, date(2026, 2, 28))
    assert schedule.next_due_date == date(2026, 3, 31)

    year_end = schedules.create_schedule(
        "Annual bill", account.id, "50", "Expense", date(2026, 12, 31)
    )
    schedules.post_due(year_end.id, date(2026, 12, 31))
    assert year_end.next_due_date == date(2027, 1, 31)


def test_scheduled_transaction_pause_and_overdue_occurrences(session):
    account = AccountService(session).create_account("Current")
    schedules = ScheduledTransactionService(session)
    schedule = schedules.create_schedule(
        "Monthly bill", account.id, "25", "Expense", date(2026, 1, 15)
    )
    schedules.set_active(schedule.id, False)
    assert schedules.due_schedules(date(2026, 2, 15)) == []
    with pytest.raises(ValueError, match="paused"):
        schedules.post_due(schedule.id, date(2026, 2, 15))

    schedules.set_active(schedule.id, True)
    first = schedules.post_due(schedule.id, date(2026, 2, 15))
    second = schedules.post_due(schedule.id, date(2026, 2, 15))
    assert first.transaction_date == date(2026, 1, 15)
    assert second.transaction_date == date(2026, 2, 15)
    assert schedule.next_due_date == date(2026, 3, 15)


def test_reports_group_by_currency_category_and_account(session):
    accounts = AccountService(session)
    eur = accounts.create_account("Euro", currency="EUR")
    usd = accounts.create_account("Dollar", currency="USD")
    food = CategoryService(session).create_category("Food", "Expense")
    tx = TransactionService(session)
    tx.add_transaction(eur.id, date(2026, 3, 1), "10", "Expense", category_id=food.id)
    tx.add_transaction(eur.id, date(2026, 3, 2), "5", "Expense")
    tx.add_transaction(usd.id, date(2026, 3, 3), "100", "Income")
    reports = ReportService(session)
    span = (date(2026, 3, 1), date(2026, 3, 31))
    totals = reports.income_expense(*span)
    assert totals["EUR"]["expenses_minor"] == 1500
    assert totals["USD"]["income_minor"] == 10000
    assert list(reports.income_expense(*span, account_id=usd.id)) == ["USD"]
    breakdown = {(r["currency"], r["category"]): r["expenses_minor"]
                 for r in reports.category_breakdown(*span)}
    assert breakdown[("EUR", "Food")] == 1000
    assert breakdown[("EUR", "Uncategorised")] == 500
    assert len(reports.transactions(*span)) == 3


def test_monthly_totals_fills_months_and_filters_currency(session):
    account = AccountService(session).create_account('Cur', currency='EUR')
    other = AccountService(session).create_account('Usd', currency='USD')
    tx = TransactionService(session)
    tx.add_transaction(account.id, date(2025, 1, 5), '100', 'Income')
    tx.add_transaction(account.id, date(2025, 3, 5), '40', 'Expense')
    tx.add_transaction(other.id, date(2025, 2, 5), '9', 'Expense')
    rows = ReportService(session).monthly_totals(date(2025, 1, 1), date(2025, 4, 30), 'EUR')
    assert rows == [('2025-01', 10000, 0), ('2025-02', 0, 0), ('2025-03', 0, 4000), ('2025-04', 0, 0)]
