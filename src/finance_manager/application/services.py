"""Application services for accounts, transactions, imports, and reports."""

import calendar
import hashlib
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import uuid4

from sqlalchemy import select

from finance_manager.domain.enums import AccountType, TransactionType
from finance_manager.domain.money import to_minor_units
from finance_manager.infrastructure.models import (
    AccountModel,
    CategoryModel,
    ImportBatchModel,
    ScheduledTransactionModel,
    ScheduledTransferModel,
    TransactionModel,
)
from finance_manager.infrastructure.repositories import (
    AccountRepository,
    CategoryRepository,
    PayeeRepository,
    TransactionRepository,
)


class AccountService:
    """Manage account creation, updates, archiving, and balances."""

    def __init__(self, session):
        self.session = session
        self.repo = AccountRepository(session)

    def create_account(self, name, account_type=AccountType.CURRENT.value,
                       opening_balance="0.00", currency="EUR"):
        """Validate, persist, and return a new account."""
        if not name.strip():
            raise ValueError("Account name is required")
        if account_type not in [t.value for t in AccountType]:
            raise ValueError("Unknown account type")
        if len(currency) != 3:
            raise ValueError("Currency must be a 3-letter code")
        account = AccountModel(
            name=name.strip(), account_type=account_type, currency=currency.upper(),
            opening_balance_minor=to_minor_units(opening_balance)
        )
        self.repo.add(account)
        self.session.commit()
        return account

    def list_accounts(self, active_only=False):
        """Return accounts, optionally limited to active accounts."""
        accounts = self.repo.list()
        return [a for a in accounts if a.is_active] if active_only else accounts

    def set_active(self, account_id, active: bool):
        """Archive (False) or restore (True) an account without touching its history."""
        account = self.repo.get(account_id)
        if account is None:
            raise ValueError("Account not found")
        account.is_active = active
        self.session.commit()
        return account

    def update_account(self, account_id, name, account_type, opening_balance, currency):
        """Edit an account; its currency is locked once it has transactions."""
        account = self.repo.get(account_id)
        if account is None:
            raise ValueError("Account not found")
        if not name.strip():
            raise ValueError("Account name is required")
        if account_type not in [t.value for t in AccountType]:
            raise ValueError("Unknown account type")
        if (account.account_type == AccountType.PENSION.value) != (
            account_type == AccountType.PENSION.value
        ):
            raise ValueError(
                "Pension accounts cannot be converted to or from another type"
            )
        if len(currency.strip()) != 3:
            raise ValueError("Currency must be a 3-letter code")
        new_currency = currency.strip().upper()
        if new_currency != account.currency and self._has_transactions(account_id):
            raise ValueError("Currency cannot be changed once an account has transactions")
        try:
            account.name = name.strip()
            account.account_type = account_type
            account.opening_balance_minor = to_minor_units(opening_balance)
            account.currency = new_currency
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return account

    def delete_account(self, account_id):
        """Delete an account that has no transactions."""
        account = self.repo.get(account_id)
        if account is None:
            raise ValueError("Account not found")
        if self._has_transactions(account_id):
            raise ValueError(
                "This account has transactions. Delete or move them before deleting the account"
            )
        try:
            self.session.delete(account)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def _has_transactions(self, account_id) -> bool:
        return self.session.scalar(
            select(TransactionModel.id).where(TransactionModel.account_id == account_id).limit(1)
        ) is not None

    def balance(self, account_id):
        return self.repo.balance_minor(account_id)


class CategoryService:
    """Manage income and expense categories."""

    def __init__(self, session):
        self.session = session
        self.repo = CategoryRepository(session)

    def create_category(self, name, kind="Expense", parent_id=None):
        """Validate, persist, and return a new category."""
        if kind not in ("Income", "Expense"):
            raise ValueError("Category kind must be Income or Expense")
        if not name.strip():
            raise ValueError("Category name is required")
        category = CategoryModel(name=name.strip(), kind=kind, parent_id=parent_id)
        self.repo.add(category)
        self.session.commit()
        return category

    def list_categories(self):
        return self.repo.list()


class PensionService:
    """Record contributions, withdrawals, and valuation changes."""

    def __init__(self, session):
        self.session = session

    def add_activity(self, account_id, tx_date, amount, activity, memo=""):
        """Add a signed activity to an active pension account."""
        account = self.session.get(AccountModel, account_id)
        if account is None or account.account_type != AccountType.PENSION.value:
            raise ValueError("A pension account is required")
        if not account.is_active:
            raise ValueError("Pension account is archived")
        signs = {
            "Contribution": 1,
            "Withdrawal": -1,
            "Valuation gain": 1,
            "Valuation loss": -1,
        }
        if activity not in signs:
            raise ValueError("Unknown pension activity")
        minor = to_minor_units(amount)
        if minor <= 0:
            raise ValueError("Amount must be greater than zero")
        tx = TransactionModel(
            account_id=account_id,
            transaction_date=tx_date,
            signed_amount_minor=signs[activity] * minor,
            transaction_type=activity,
            memo=(memo or "").strip(),
        )
        self.session.add(tx)
        self.session.commit()
        return tx


class TransactionService:
    """Create and manage income and expense ledger transactions."""

    def __init__(self, session):
        self.session = session
        self.accounts = AccountRepository(session)
        self.categories = CategoryRepository(session)
        self.payees = PayeeRepository(session)
        self.transactions = TransactionRepository(session)

    def add_transaction(self, account_id: int, tx_date: date, amount,
                        transaction_type: str, payee="", memo="",
                        category_id=None, reference=""):
        """Validate and persist an income or expense transaction."""
        if transaction_type not in (TransactionType.INCOME.value, TransactionType.EXPENSE.value):
            raise ValueError("Use TransferService to create transfers")
        account = self.accounts.get(account_id)
        if account is None:
            raise ValueError("Account not found")
        if not account.is_active:
            raise ValueError("Account is archived; restore it to add transactions")
        magnitude = to_minor_units(amount)
        if magnitude <= 0:
            raise ValueError("Amount must be greater than zero")
        if (
            category_id is not None
            and self.session.get(CategoryModel, category_id) is None
        ):
            raise ValueError("Category not found")
        signed = magnitude if transaction_type == "Income" else -magnitude
        self.payees.get_or_create(payee)
        tx = TransactionModel(
            account_id=account_id, transaction_date=tx_date,
            signed_amount_minor=signed, transaction_type=transaction_type,
            payee_text=(payee or "").strip(), memo=(memo or "").strip(),
            reference=(reference or "").strip(), category_id=category_id
        )
        self.transactions.add(tx)
        self.session.commit()
        return tx

    def list_transactions(self, account_id=None, search=""):
        """Return transactions matching the optional account and search filters."""
        return self.transactions.list(account_id, search)

    def update_transaction(self, transaction_id: int, account_id: int, tx_date: date,
                           amount, transaction_type: str, payee="", memo="",
                           category_id=None):
        """Edit an Income/Expense transaction; transfers must be deleted and recreated."""
        tx = self.session.get(TransactionModel, transaction_id)
        if tx is None:
            raise ValueError("Transaction not found")
        if tx.transfer_id is not None or tx.transaction_type == "Transfer":
            raise ValueError("Transfers cannot be edited; delete and recreate the transfer")
        if transaction_type not in (TransactionType.INCOME.value, TransactionType.EXPENSE.value):
            raise ValueError("Transaction type must be Income or Expense")
        target = self.accounts.get(account_id)
        if target is None:
            raise ValueError("Account not found")
        if not target.is_active and account_id != tx.account_id:
            raise ValueError("Cannot move a transaction to an archived account")
        magnitude = to_minor_units(amount)
        if magnitude <= 0:
            raise ValueError("Amount must be greater than zero")
        if category_id is not None and self.session.get(CategoryModel, category_id) is None:
            raise ValueError("Category not found")
        try:
            self.payees.get_or_create(payee)
            tx.account_id = account_id
            tx.transaction_date = tx_date
            tx.signed_amount_minor = magnitude if transaction_type == "Income" else -magnitude
            tx.transaction_type = transaction_type
            tx.payee_text = (payee or "").strip()
            tx.memo = (memo or "").strip()
            tx.category_id = category_id
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return tx

    def delete_transaction(self, transaction_id: int) -> int:
        """Delete a transaction; both legs of a transfer are removed together.

        Returns the number of rows deleted.
        """
        tx = self.session.get(TransactionModel, transaction_id)
        if tx is None:
            raise ValueError("Transaction not found")
        try:
            if tx.transfer_id is not None:
                rows = list(self.session.scalars(
                    select(TransactionModel).where(
                        TransactionModel.transfer_id == tx.transfer_id
                    )
                ))
            else:
                rows = [tx]
            for row in rows:
                self.session.delete(row)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return len(rows)


class TransferService:
    """Create paired ledger entries for transfers between accounts."""

    def __init__(self, session):
        self.session = session
        self.accounts = AccountRepository(session)

    @staticmethod
    def _parse_rate(value) -> Decimal:
        """Parse and validate a positive exchange rate."""
        try:
            rate = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("An exchange rate is required for cross-currency transfers") from exc
        if not rate.is_finite() or rate <= 0:
            raise ValueError("Exchange rate must be greater than zero")
        return rate

    @staticmethod
    def convert_minor(minor: int, rate: Decimal) -> int:
        """Convert minor units at rate, rounding half up to the nearest cent."""
        return int((Decimal(minor) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    def _accounts(self, source_id, destination_id):
        if source_id == destination_id:
            raise ValueError("Source and destination accounts must differ")
        source = self.accounts.get(source_id)
        destination = self.accounts.get(destination_id)
        if source is None or destination is None:
            raise ValueError("Both accounts must exist")
        if not (source.is_active and destination.is_active):
            raise ValueError("Archived accounts cannot be used in transfers")
        return source, destination

    def _add_transfer(self, source_id, destination_id, amount, tx_date, memo="",
                      exchange_rate=None):
        source, destination = self._accounts(source_id, destination_id)
        minor = to_minor_units(amount)
        if minor <= 0:
            raise ValueError("Transfer amount must be greater than zero")
        destination_minor = minor
        if source.currency != destination.currency:
            rate = self._parse_rate(exchange_rate)
            destination_minor = self.convert_minor(minor, rate)
            if destination_minor <= 0:
                raise ValueError("Converted amount is too small")
            memo = (f"{memo} ".lstrip() +
                    f"[1 {source.currency} = {rate.normalize():f} {destination.currency}]")
        transfer_id = str(uuid4())
        debit = TransactionModel(
            account_id=source_id, transaction_date=tx_date,
            signed_amount_minor=-minor, transaction_type="Transfer",
            payee_text=f"Transfer to {destination.name}", memo=memo,
            transfer_id=transfer_id
        )
        credit = TransactionModel(
            account_id=destination_id, transaction_date=tx_date,
            signed_amount_minor=destination_minor, transaction_type="Transfer",
            payee_text=f"Transfer from {source.name}", memo=memo,
            transfer_id=transfer_id
        )
        self.session.add_all([debit, credit])
        return debit

    def create_transfer(self, source_id: int, destination_id: int, amount,
                        tx_date: date, memo="", exchange_rate=None):
        """Move funds between accounts; rate is destination units per source unit."""
        try:
            debit = self._add_transfer(
                source_id, destination_id, amount, tx_date, memo, exchange_rate
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return debit.transfer_id


class ScheduledTransactionService:
    """Manage recurring income, expense, and transfer reminders."""

    def __init__(self, session):
        self.session = session

    def create_schedule(self, name, account_id, amount, transaction_type, due_date,
                        category_id=None, payee="", memo="", destination_id=None):
        """Validate and persist a recurring transaction schedule."""
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Schedule name is required")
        if transaction_type not in (
            TransactionType.INCOME.value, TransactionType.EXPENSE.value,
            TransactionType.TRANSFER.value,
        ):
            raise ValueError("Transaction type must be Income, Expense or Transfer")
        account = self.session.get(AccountModel, account_id)
        if account is None or not account.is_active:
            raise ValueError("An active account is required")
        amount_minor = to_minor_units(amount)
        if amount_minor <= 0:
            raise ValueError("Amount must be greater than zero")
        if transaction_type == TransactionType.TRANSFER.value:
            if destination_id is None:
                raise ValueError("A destination account is required")
            TransferService(self.session)._accounts(account_id, destination_id)
            if category_id is not None or payee.strip():
                raise ValueError("Transfers cannot have a category or payee")
        elif destination_id is not None:
            raise ValueError("Destination is only valid for a transfer")
        if (
            category_id is not None
            and self.session.get(CategoryModel, category_id) is None
        ):
            raise ValueError("Category not found")

        schedule = ScheduledTransactionModel(
            name=clean_name,
            account_id=account_id,
            category_id=category_id,
            amount_minor=amount_minor,
            transaction_type=transaction_type,
            payee_text=(payee or "").strip(),
            memo=(memo or "").strip(),
            next_due_date=due_date,
            due_day=due_date.day,
        )
        if transaction_type == TransactionType.TRANSFER.value:
            schedule.transfer = ScheduledTransferModel(
                destination_account_id=destination_id
            )
        self.session.add(schedule)
        self.session.commit()
        return schedule

    def list_schedules(self, active_only=False):
        """Return schedules ordered by due date and name."""
        stmt = select(ScheduledTransactionModel).order_by(
            ScheduledTransactionModel.next_due_date,
            ScheduledTransactionModel.name,
        )
        if active_only:
            stmt = stmt.where(ScheduledTransactionModel.is_active.is_(True))
        return list(self.session.scalars(stmt))

    def due_schedules(self, as_of=None):
        """Return active schedules due on or before the specified date."""
        as_of = as_of or date.today()
        stmt = (
            select(ScheduledTransactionModel)
            .where(
                ScheduledTransactionModel.is_active.is_(True),
                ScheduledTransactionModel.next_due_date <= as_of,
            )
            .order_by(
                ScheduledTransactionModel.next_due_date,
                ScheduledTransactionModel.name,
            )
        )
        return list(self.session.scalars(stmt))

    def set_active(self, schedule_id, active: bool):
        schedule = self.session.get(ScheduledTransactionModel, schedule_id)
        if schedule is None:
            raise ValueError("Scheduled transaction not found")
        schedule.is_active = active
        self.session.commit()
        return schedule

    def post_due(self, schedule_id, as_of=None, exchange_rate=None):
        """Post one due occurrence and advance its schedule by one month."""
        as_of = as_of or date.today()
        schedule = self.session.get(ScheduledTransactionModel, schedule_id)
        if schedule is None:
            raise ValueError("Scheduled transaction not found")
        if not schedule.is_active:
            raise ValueError("Scheduled transaction is paused")
        if schedule.next_due_date > as_of:
            raise ValueError("Scheduled transaction is not due yet")

        account = self.session.get(AccountModel, schedule.account_id)
        if account is None or not account.is_active:
            raise ValueError("The scheduled account is not active")
        try:
            if schedule.transaction_type == TransactionType.TRANSFER.value:
                if schedule.transfer is None:
                    raise ValueError("Scheduled transfer has no destination")
                transaction = TransferService(self.session)._add_transfer(
                    schedule.account_id, schedule.transfer.destination_account_id,
                    Decimal(schedule.amount_minor) / 100, schedule.next_due_date,
                    schedule.memo, exchange_rate,
                )
            else:
                signed_amount = (
                    schedule.amount_minor
                    if schedule.transaction_type == TransactionType.INCOME.value
                    else -schedule.amount_minor
                )
                transaction = TransactionModel(
                    account_id=schedule.account_id,
                    transaction_date=schedule.next_due_date,
                    signed_amount_minor=signed_amount,
                    transaction_type=schedule.transaction_type,
                    payee_text=schedule.payee_text or schedule.name,
                    memo=schedule.memo,
                    category_id=schedule.category_id,
                )
                self.session.add(transaction)
            next_month = schedule.next_due_date.month % 12 + 1
            next_year = schedule.next_due_date.year
            if schedule.next_due_date.month == 12:
                next_year += 1
            next_day = min(
                schedule.due_day, calendar.monthrange(next_year, next_month)[1]
            )
            schedule.next_due_date = date(next_year, next_month, next_day)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return transaction


class ReportService:
    """Generate income, expense, category, and transaction reports."""

    def __init__(self, session):
        self.session = session

    def _rows(self, start_date: date, end_date: date, account_id=None):
        """Income/Expense rows in range with account currency and category name."""
        stmt = (
            select(TransactionModel, AccountModel.currency, CategoryModel.name)
            .join(AccountModel, AccountModel.id == TransactionModel.account_id)
            .outerjoin(CategoryModel, CategoryModel.id == TransactionModel.category_id)
            .where(
                TransactionModel.transaction_date >= start_date,
                TransactionModel.transaction_date <= end_date,
                TransactionModel.transaction_type.in_(["Income", "Expense"]),
                AccountModel.account_type != AccountType.PENSION.value,
            )
            .order_by(TransactionModel.transaction_date, TransactionModel.id)
        )
        if account_id is not None:
            stmt = stmt.where(TransactionModel.account_id == account_id)
        return self.session.execute(stmt).all()

    def income_expense(self, start_date: date, end_date: date, account_id=None):
        """Totals per currency, since amounts in different currencies cannot be added."""
        totals: dict[str, dict[str, int]] = {}
        for tx, currency, _ in self._rows(start_date, end_date, account_id):
            entry = totals.setdefault(
                currency, {"income_minor": 0, "expenses_minor": 0, "net_minor": 0}
            )
            amount = tx.signed_amount_minor
            if amount > 0:
                entry["income_minor"] += amount
            else:
                # Expenses are negative in the ledger; report them as a positive total.
                entry["expenses_minor"] -= amount
            entry["net_minor"] += amount
        return dict(sorted(totals.items()))

    def category_breakdown(self, start_date: date, end_date: date, account_id=None):
        """Income and expense totals per currency and category."""
        groups: dict[tuple[str, str], dict[str, int]] = {}
        for tx, currency, category in self._rows(start_date, end_date, account_id):
            entry = groups.setdefault(
                (currency, category or "Uncategorised"),
                {"income_minor": 0, "expenses_minor": 0},
            )
            if tx.signed_amount_minor > 0:
                entry["income_minor"] += tx.signed_amount_minor
            else:
                entry["expenses_minor"] -= tx.signed_amount_minor
        return [
            {"currency": currency, "category": category, **values}
            for (currency, category), values in sorted(groups.items())
        ]

    def monthly_totals(self, start_date: date, end_date: date, currency: str,
                       account_id=None, by: str = "month"):
        """Income and expenses per period for one currency.

        by="month" returns every month from start to end, including empty ones.
        by="year" returns every year between the first and last transaction.
        Each item is (label, income_minor, expenses_minor).
        """
        buckets: dict[str, list[int]] = {}
        for tx, tx_currency, _ in self._rows(start_date, end_date, account_id):
            if tx_currency != currency:
                continue
            label = (
                tx.transaction_date.strftime("%Y-%m") if by == "month"
                else str(tx.transaction_date.year)
            )
            entry = buckets.setdefault(label, [0, 0])
            if tx.signed_amount_minor > 0:
                entry[0] += tx.signed_amount_minor
            else:
                entry[1] -= tx.signed_amount_minor
        if by == "month":
            year, month = start_date.year, start_date.month
            labels = []
            while (year, month) <= (end_date.year, end_date.month):
                labels.append(f"{year:04d}-{month:02d}")
                year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        elif buckets:
            first, last = int(min(buckets)), int(max(buckets))
            labels = [str(y) for y in range(first, last + 1)]
        else:
            labels = []
        return [(label, *buckets.get(label, [0, 0])) for label in labels]

    def transactions(self, start_date: date, end_date: date, account_id=None):
        """The Income/Expense transactions behind the report, oldest first."""
        return [tx for tx, _, _ in self._rows(start_date, end_date, account_id)]


class ImportService:
    """Import external statement records into the transaction ledger."""

    def __init__(self, session):
        self.session = session

    def commit_qif(self, filename: str, account_id: int, records: list[dict]):
        """Persist QIF records while skipping duplicate transactions."""
        account = AccountRepository(self.session).get(account_id)
        if account is None:
            raise ValueError("Destination account not found")
        batch = ImportBatchModel(filename=filename, file_format="QIF")
        self.session.add(batch)
        self.session.flush()
        tx_repo = TransactionRepository(self.session)
        cat_repo = CategoryRepository(self.session)
        payees = PayeeRepository(self.session)
        imported = 0
        skipped = 0
        try:
            for record in records:
                signed = to_minor_units(record["amount"])
                kind = "Income" if signed >= 0 else "Expense"
                category_id = None
                raw_category = (record.get("category") or "").strip()
                payee = (record.get("payee") or "").strip()
                transfer_account = None
                if raw_category.startswith("[") and raw_category.endswith("]"):
                    # QIF marks a transfer to another account as "[Account name]".
                    transfer_account = raw_category[1:-1].strip()
                    kind = "Transfer"
                    if not payee:
                        direction = "from" if signed >= 0 else "to"
                        payee = f"Transfer {direction} {transfer_account}"
                category_name = raw_category.split("/")[-1].strip()
                if category_name and transfer_account is None:
                    category = cat_repo.find_by_name(category_name)
                    if category is None:
                        category = cat_repo.add(
                            CategoryModel(name=category_name, kind=kind)
                        )
                    category_id = category.id
                memo = (record.get("memo") or "").strip()
                if tx_repo.duplicate_exists(
                    account_id, record["date"], signed, payee, memo
                ):
                    skipped += 1
                    continue
                payees.get_or_create(payee)
                tx_repo.add(TransactionModel(
                    account_id=account_id,
                    transaction_date=record["date"],
                    signed_amount_minor=signed,
                    transaction_type=kind,
                    payee_text=payee, memo=memo,
                    reference=record.get("reference", ""),
                    category_id=category_id,
                    import_batch_id=batch.id
                ))
                imported += 1
            batch.imported_count = imported
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return {"imported": imported, "skipped": skipped, "batch_id": batch.id}

    def commit_revolut(self, filename: str, account_id: int, records: list[dict]):
        """Import Revolut statement rows into one account.

        Pending rows are ignored. Card payments and top-ups become Expense/Income;
        transfers and currency exchanges are booked as Transfer so reports
        exclude them. Rows already imported are recognised by a reference built
        from the row's timestamps, amount and description.
        """
        account = AccountRepository(self.session).get(account_id)
        if account is None:
            raise ValueError("Destination account not found")
        wrong = {r["currency"] for r in records if r["currency"] != account.currency}
        if wrong:
            raise ValueError(
                f"Statement currency {', '.join(sorted(wrong))} does not match "
                f"account currency {account.currency}"
            )
        batch = ImportBatchModel(filename=filename, file_format="REVOLUT")
        self.session.add(batch)
        self.session.flush()
        tx_repo = TransactionRepository(self.session)
        payees = PayeeRepository(self.session)
        imported = skipped = pending = 0
        seen: dict[str, int] = {}
        try:
            for record in records:
                if record["state"] != "COMPLETED" or record["completed"] is None:
                    pending += 1
                    continue
                # A fee is deducted from the balance on top of the amount.
                signed = to_minor_units(record["amount"] - record["fee"])
                if record["type"] in ("Transfer", "Exchange"):
                    kind = "Transfer"
                else:
                    kind = "Income" if signed >= 0 else "Expense"
                key = "|".join([
                    record["started"].isoformat(), record["completed"].isoformat(),
                    str(record["amount"]), record["description"], record["type"],
                ])
                seen[key] = seen.get(key, 0) + 1
                reference = "REV-" + hashlib.sha1(
                    f"{key}|{seen[key]}".encode()
                ).hexdigest()[:20]
                if tx_repo.reference_exists(account_id, reference):
                    skipped += 1
                    continue
                payee = record["description"]
                payees.get_or_create(payee)
                tx_repo.add(TransactionModel(
                    account_id=account_id,
                    transaction_date=record["started"].date(),
                    signed_amount_minor=signed,
                    transaction_type=kind,
                    payee_text=payee,
                    memo=f"Revolut {record['type']}"
                         + (f" (fee {record['fee']})" if record["fee"] else ""),
                    reference=reference,
                    import_batch_id=batch.id,
                ))
                imported += 1
            batch.imported_count = imported
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return {
            "imported": imported, "skipped": skipped, "pending": pending,
            "batch_id": batch.id,
        }
