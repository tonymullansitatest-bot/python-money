from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from finance_manager.domain.enums import AccountType, TransactionType
from finance_manager.domain.money import to_minor_units
from finance_manager.infrastructure.models import (
    AccountModel, CategoryModel, ImportBatchModel, TransactionModel
)
from finance_manager.infrastructure.repositories import (
    AccountRepository, CategoryRepository, PayeeRepository, TransactionRepository
)


class AccountService:
    def __init__(self, session):
        self.session = session
        self.repo = AccountRepository(session)

    def create_account(self, name, account_type=AccountType.CURRENT.value,
                       opening_balance="0.00", currency="EUR"):
        if not name.strip():
            raise ValueError("Account name is required")
        if len(currency) != 3:
            raise ValueError("Currency must be a 3-letter code")
        account = AccountModel(
            name=name.strip(), account_type=account_type, currency=currency.upper(),
            opening_balance_minor=to_minor_units(opening_balance)
        )
        self.repo.add(account)
        self.session.commit()
        return account

    def list_accounts(self):
        return self.repo.list()

    def balance(self, account_id):
        return self.repo.balance_minor(account_id)


class CategoryService:
    def __init__(self, session):
        self.session = session
        self.repo = CategoryRepository(session)

    def create_category(self, name, kind="Expense", parent_id=None):
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


class TransactionService:
    def __init__(self, session):
        self.session = session
        self.accounts = AccountRepository(session)
        self.categories = CategoryRepository(session)
        self.payees = PayeeRepository(session)
        self.transactions = TransactionRepository(session)

    def add_transaction(self, account_id: int, tx_date: date, amount,
                        transaction_type: str, payee="", memo="",
                        category_id=None, reference=""):
        if transaction_type not in (TransactionType.INCOME.value, TransactionType.EXPENSE.value):
            raise ValueError("Use TransferService to create transfers")
        if self.accounts.get(account_id) is None:
            raise ValueError("Account not found")
        magnitude = to_minor_units(amount)
        if magnitude <= 0:
            raise ValueError("Amount must be greater than zero")
        if category_id is not None and self.session.get(CategoryModel, category_id) is None:
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
        return self.transactions.list(account_id, search)


class TransferService:
    def __init__(self, session):
        self.session = session
        self.accounts = AccountRepository(session)

    def create_transfer(self, source_id: int, destination_id: int, amount,
                        tx_date: date, memo=""):
        if source_id == destination_id:
            raise ValueError("Source and destination accounts must differ")
        source = self.accounts.get(source_id)
        destination = self.accounts.get(destination_id)
        if source is None or destination is None:
            raise ValueError("Both accounts must exist")
        if source.currency != destination.currency:
            raise ValueError("Cross-currency transfers are not supported yet")
        minor = to_minor_units(amount)
        if minor <= 0:
            raise ValueError("Transfer amount must be greater than zero")
        transfer_id = str(uuid4())
        try:
            self.session.add_all([
                TransactionModel(
                    account_id=source_id, transaction_date=tx_date,
                    signed_amount_minor=-minor, transaction_type="Transfer",
                    payee_text=f"Transfer to {destination.name}", memo=memo,
                    transfer_id=transfer_id
                ),
                TransactionModel(
                    account_id=destination_id, transaction_date=tx_date,
                    signed_amount_minor=minor, transaction_type="Transfer",
                    payee_text=f"Transfer from {source.name}", memo=memo,
                    transfer_id=transfer_id
                )
            ])
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return transfer_id


class ReportService:
    def __init__(self, session):
        self.session = session

    def income_expense(self, start_date: date, end_date: date):
        rows = self.session.scalars(
            select(TransactionModel).where(
                TransactionModel.transaction_date >= start_date,
                TransactionModel.transaction_date <= end_date,
                TransactionModel.transaction_type.in_(["Income", "Expense"])
            )
        )
        income = sum((x.signed_amount_minor for x in rows if x.signed_amount_minor > 0), 0)
        # Expense entries are negative in the ledger; report them as a positive total.
        expenses = -sum((x.signed_amount_minor for x in self.session.scalars(
            select(TransactionModel).where(
                TransactionModel.transaction_date >= start_date,
                TransactionModel.transaction_date <= end_date,
                TransactionModel.transaction_type == "Expense"
            )
        )), 0)
        return {
            "income_minor": income,
            "expenses_minor": expenses,
            "net_minor": income - expenses,
        }


class ImportService:
    def __init__(self, session):
        self.session = session

    def commit_qif(self, filename: str, account_id: int, records: list[dict]):
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
                magnitude = to_minor_units(record["amount"])
                signed = magnitude if magnitude >= 0 else magnitude
                kind = "Income" if signed >= 0 else "Expense"
                category_id = None
                category_name = (record.get("category") or "").split("/")[-1].strip()
                if category_name:
                    category = cat_repo.find_by_name(category_name)
                    if category is None:
                        category = cat_repo.add(
                            CategoryModel(name=category_name, kind=kind)
                        )
                    category_id = category.id
                payee = (record.get("payee") or "").strip()
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
