from datetime import date
from decimal import Decimal

import pytest

from finance_manager.application.services import (
    AccountService,
    CategoryService,
    PensionService,
    ReportService,
    ScheduledTransactionService,
    TransactionService,
    TransferService,
)
from finance_manager.domain.enums import AccountType
from finance_manager.infrastructure.database import build_session_factory
from finance_manager.infrastructure.models import TransactionModel
from finance_manager.infrastructure.repositories import PayeeRepository


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


def test_payee_suggestions_include_legacy_transactions_and_persist_scheduled_payees(
    session,
):
    account = AccountService(session).create_account("Current")
    transactions = TransactionService(session)
    tx = transactions.add_transaction(
        account.id, date.today(), "1", "Expense", "  Shop  "
    )
    transactions.add_transaction(account.id, date.today(), "1", "Expense", "shop")
    session.add(TransactionModel(
        account_id=account.id, transaction_date=date.today(),
        signed_amount_minor=-100, transaction_type="Expense", payee_text=" Legacy ",
    ))
    session.add(TransactionModel(
        account_id=account.id, transaction_date=date.today(),
        signed_amount_minor=-100, transaction_type="Transfer",
        payee_text="Transfer to B",
    ))
    session.commit()
    schedules = ScheduledTransactionService(session)
    schedule = schedules.create_schedule(
        "Bill", account.id, "1", "Expense", date.today(), payee="Power"
    )
    posted = schedules.post_due(schedule.id, date.today())
    transactions.delete_transaction(tx.id)
    transactions.delete_transaction(posted.id)

    factory = build_session_factory(session.get_bind())
    with factory() as fresh_session:
        assert PayeeRepository(fresh_session).list_names() == [
            "Legacy", "Power", "Shop"
        ]


def test_transfer_is_balanced_and_not_income_expense(session):
    service = AccountService(session)
    a = service.create_account("Current")
    b = service.create_account("Savings", AccountType.SAVINGS.value)
    TransferService(session).create_transfer(a.id, b.id, "25.00", date(2026, 2, 1))
    assert service.balance(a.id) == -2500
    assert service.balance(b.id) == 2500
    report = ReportService(session).income_expense(date(2026, 1, 1), date(2026, 12, 31))
    assert report == {}


def test_pension_activity_transfers_and_reporting_are_separate(session):
    accounts = AccountService(session)
    current = accounts.create_account("Current", opening_balance="1000")
    pension = accounts.create_account("Pension", AccountType.PENSION.value, "500")
    activities = PensionService(session)
    TransferService(session).create_transfer(
        current.id, pension.id, "100", date(2026, 1, 1)
    )
    activities.add_activity(pension.id, date(2026, 1, 2), "50", "Contribution")
    activities.add_activity(pension.id, date(2026, 1, 3), "20", "Withdrawal")
    activities.add_activity(pension.id, date(2026, 1, 4), "30", "Valuation gain")
    activities.add_activity(pension.id, date(2026, 1, 5), "10", "Valuation loss")
    # Imported pension records can still use ordinary income/expense types.
    TransactionService(session).add_transaction(
        pension.id, date(2026, 1, 6), "5", "Income"
    )
    TransactionService(session).add_transaction(
        current.id, date(2026, 1, 7), "200", "Income"
    )
    assert accounts.balance(current.id) == 110000
    assert accounts.balance(pension.id) == 65500
    reports = ReportService(session)
    span = (date(2026, 1, 1), date(2026, 1, 31))
    assert reports.income_expense(*span) == {
        "EUR": {"income_minor": 20000, "expenses_minor": 0, "net_minor": 20000}
    }
    assert reports.income_expense(*span, account_id=pension.id) == {}
    assert len(reports.transactions(*span)) == 1
    assert reports.category_breakdown(*span)[0]["income_minor"] == 20000
    assert reports.monthly_totals(*span, "EUR") == [("2026-01", 20000, 0)]


def test_pension_activity_validation_and_account_type_lock(session):
    accounts = AccountService(session)
    current = accounts.create_account("Current")
    pension = accounts.create_account("Pension", AccountType.PENSION.value)
    service = PensionService(session)
    with pytest.raises(ValueError, match="pension account"):
        service.add_activity(current.id, date.today(), "1", "Contribution")
    with pytest.raises(ValueError, match="greater than zero"):
        service.add_activity(pension.id, date.today(), "0", "Contribution")
    with pytest.raises(ValueError, match="Unknown pension activity"):
        service.add_activity(pension.id, date.today(), "1", "Income")
    with pytest.raises(ValueError, match="cannot be converted"):
        accounts.update_account(pension.id, "Pension", "Savings", "0", "EUR")
    with pytest.raises(ValueError, match="cannot be converted"):
        accounts.update_account(current.id, "Current", "Pension", "0", "EUR")
    accounts.set_active(pension.id, False)
    with pytest.raises(ValueError, match="archived"):
        service.add_activity(pension.id, date.today(), "1", "Contribution")


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


def test_scheduled_transfer_posts_linked_entries_and_advances(session):
    accounts = AccountService(session)
    source = accounts.create_account("Current", opening_balance="1000")
    destination = accounts.create_account("Loan", AccountType.LOAN.value, "-5000")
    schedules = ScheduledTransactionService(session)
    schedule = schedules.create_schedule(
        "Loan principal", source.id, "300", "Transfer", date(2026, 1, 31),
        memo="Principal", destination_id=destination.id,
    )
    assert accounts.balance(source.id) == 100000
    with pytest.raises(ValueError, match="not due"):
        schedules.post_due(schedule.id, date(2026, 1, 30))
    posted = schedules.post_due(schedule.id, date(2026, 1, 31))
    rows = TransactionService(session).list_transactions()
    assert len(rows) == 2
    assert {row.transfer_id for row in rows} == {posted.transfer_id}
    assert {row.signed_amount_minor for row in rows} == {-30000, 30000}
    assert all(row.memo == "Principal" for row in rows)
    assert (accounts.balance(source.id), accounts.balance(destination.id)) == (
        70000, -470000
    )
    assert schedule.next_due_date == date(2026, 2, 28)
    assert ReportService(session).income_expense(
        date(2026, 1, 1), date(2026, 1, 31)
    ) == {}
    assert TransactionService(session).delete_transaction(posted.id) == 2


def test_scheduled_transfer_validates_accounts_and_posting_rate(session):
    accounts = AccountService(session)
    source = accounts.create_account("Euro")
    destination = accounts.create_account("Dollar", currency="USD")
    schedules = ScheduledTransactionService(session)
    for destination_id in (None, source.id, 99999):
        with pytest.raises(ValueError):
            schedules.create_schedule(
                "Transfer", source.id, "100", "Transfer", date(2026, 1, 1),
                destination_id=destination_id,
            )
    schedule = schedules.create_schedule(
        "Transfer", source.id, "100", "Transfer", date(2026, 1, 1),
        destination_id=destination.id,
    )
    with pytest.raises(ValueError, match="exchange rate"):
        schedules.post_due(schedule.id, date(2026, 1, 1))
    assert schedule.next_due_date == date(2026, 1, 1)
    assert accounts.balance(source.id) == accounts.balance(destination.id) == 0
    accounts.set_active(destination.id, False)
    with pytest.raises(ValueError, match="Archived"):
        schedules.post_due(schedule.id, date(2026, 1, 1), exchange_rate="1.2")
    accounts.set_active(destination.id, True)
    schedules.post_due(schedule.id, date(2026, 1, 1), exchange_rate="1.2")
    assert (accounts.balance(source.id), accounts.balance(destination.id)) == (
        -10000, 12000
    )
    schedules.post_due(schedule.id, date(2026, 2, 1), exchange_rate="1.1")
    assert (accounts.balance(source.id), accounts.balance(destination.id)) == (
        -20000, 23000
    )


def test_scheduled_transfer_failed_commit_rolls_back_both_legs_and_due_date(
    session, monkeypatch
):
    accounts = AccountService(session)
    source = accounts.create_account("Source")
    destination = accounts.create_account("Destination")
    schedules = ScheduledTransactionService(session)
    schedule = schedules.create_schedule(
        "Transfer", source.id, "100", "Transfer", date(2026, 1, 1),
        destination_id=destination.id,
    )
    schedule_id = schedule.id

    def fail_commit():
        session.flush()
        raise RuntimeError("Commit failed")

    monkeypatch.setattr(session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="Commit failed"):
        schedules.post_due(schedule_id, date(2026, 1, 1))
    assert session.get(type(schedule), schedule_id).next_due_date == date(2026, 1, 1)
    assert TransactionService(session).list_transactions() == []
    assert accounts.balance(source.id) == accounts.balance(destination.id) == 0


def test_forecast_includes_overdue_months_boundary_and_preserves_ledger(session):
    accounts = AccountService(session)
    current = accounts.create_account("Current", opening_balance="1000")
    savings = accounts.create_account("Savings", opening_balance="200")
    schedules = ScheduledTransactionService(session)
    bill = schedules.create_schedule(
        "Bill", current.id, "10", "Expense", date(2025, 12, 31)
    )
    schedules.create_schedule(
        "Salary", current.id, "100", "Income", date(2026, 3, 14)
    )
    schedules.create_schedule(
        "Savings", current.id, "25", "Transfer", date(2026, 3, 14),
        destination_id=savings.id,
    )
    schedules.create_schedule(
        "Too late", current.id, "999", "Expense", date(2026, 3, 15)
    )
    paused = schedules.create_schedule(
        "Paused", current.id, "999", "Expense", date(2026, 3, 1)
    )
    schedules.set_active(paused.id, False)

    balances, warnings = schedules.forecast_balances(date(2026, 3, 14))
    # December, January and February bills, plus salary and both transfer legs.
    assert balances == {current.id: 104500, savings.id: 22500}
    assert warnings == []
    assert schedules.forecast_balances(date(2026, 3, 14)) == (balances, [])
    session.expire_all()
    assert bill.next_due_date == date(2025, 12, 31)
    assert TransactionService(session).list_transactions() == []
    assert accounts.balance(current.id) == 100000


def test_forecast_does_not_double_count_posted_occurrences_and_handles_pension(session):
    accounts = AccountService(session)
    current = accounts.create_account("Current", opening_balance="100")
    pension = accounts.create_account("Pension", AccountType.PENSION.value)
    schedules = ScheduledTransactionService(session)
    schedule = schedules.create_schedule(
        "Pension transfer", current.id, "20", "Transfer", date(2026, 1, 31),
        destination_id=pension.id,
    )
    schedules.post_due(schedule.id, date(2026, 1, 31))
    assert schedules.forecast_balances(date(2026, 2, 28)) == (
        {current.id: 6000, pension.id: 4000}, []
    )
    assert schedules.forecast_balances(date(2026, 3, 30)) == (
        {current.id: 6000, pension.id: 4000}, []
    )
    assert schedules.forecast_balances(date(2026, 3, 31)) == (
        {current.id: 4000, pension.id: 6000}, []
    )
    assert schedule.next_due_date == date(2026, 2, 28)
    assert len(TransactionService(session).list_transactions()) == 2


def test_forecast_warns_and_excludes_cross_currency_and_inactive_accounts(session):
    accounts = AccountService(session)
    current = accounts.create_account("Current", opening_balance="100")
    dollar = accounts.create_account("Dollar", currency="USD")
    archived = accounts.create_account("Archived")
    schedules = ScheduledTransactionService(session)
    schedules.create_schedule(
        "Foreign transfer", current.id, "20", "Transfer", date(2026, 1, 1),
        destination_id=dollar.id,
    )
    schedules.create_schedule(
        "Archived transfer", current.id, "30", "Transfer", date(2026, 1, 1),
        destination_id=archived.id,
    )
    schedules.create_schedule(
        "Archived bill", archived.id, "10", "Expense", date(2026, 1, 1)
    )
    accounts.set_active(archived.id, False)
    balances, warnings = schedules.forecast_balances(date(2026, 1, 14))
    assert balances == {current.id: 10000, dollar.id: 0}
    assert len(warnings) == 3
    assert any("exchange rate required" in warning for warning in warnings)
    assert any("destination account inactive" in warning for warning in warnings)
    assert any("source account inactive" in warning for warning in warnings)


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
