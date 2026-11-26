from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finance_manager.infrastructure.models import (
    AccountModel, CategoryModel, PayeeModel, TransactionModel
)


class AccountRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self):
        return list(self.session.scalars(select(AccountModel).order_by(AccountModel.name)))

    def get(self, account_id: int):
        return self.session.get(AccountModel, account_id)

    def add(self, account: AccountModel):
        self.session.add(account)
        self.session.flush()
        return account

    def balance_minor(self, account_id: int) -> int:
        account = self.get(account_id)
        if account is None:
            raise ValueError("Account not found")
        movement = self.session.scalar(
            select(func.coalesce(func.sum(TransactionModel.signed_amount_minor), 0))
            .where(TransactionModel.account_id == account_id)
        )
        return account.opening_balance_minor + int(movement or 0)


class CategoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self):
        return list(self.session.scalars(select(CategoryModel).order_by(CategoryModel.name)))

    def find_by_name(self, name: str, kind: str | None = None):
        stmt = select(CategoryModel).where(func.lower(CategoryModel.name) == name.lower())
        if kind:
            stmt = stmt.where(CategoryModel.kind == kind)
        return self.session.scalar(stmt)

    def add(self, category: CategoryModel):
        self.session.add(category)
        self.session.flush()
        return category


class PayeeRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_names(self) -> list[str]:
        names = {}
        saved = self.session.scalars(select(PayeeModel.name).order_by(PayeeModel.id))
        for name in saved:
            clean = name.strip()
            if clean:
                names.setdefault(clean.casefold(), clean)
        historical = self.session.scalars(
            select(TransactionModel.payee_text)
            .where(
                TransactionModel.transaction_type.in_(("Income", "Expense")),
                TransactionModel.transfer_id.is_(None),
            )
            .distinct()
            .order_by(TransactionModel.payee_text)
        )
        for name in historical:
            clean = name.strip()
            if clean:
                names.setdefault(clean.casefold(), clean)
        return sorted(names.values(), key=str.casefold)

    def get_or_create(self, name: str):
        clean = (name or "").strip()
        if not clean:
            return None
        payee = self.session.scalar(
            select(PayeeModel).where(func.lower(PayeeModel.name) == clean.lower())
        )
        if payee is None:
            payee = PayeeModel(name=clean)
            self.session.add(payee)
            self.session.flush()
        return payee


class TransactionRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self, account_id: int | None = None, search: str = ""):
        stmt = select(TransactionModel).order_by(
            TransactionModel.transaction_date.desc(), TransactionModel.id.desc()
        )
        if account_id is not None:
            stmt = stmt.where(TransactionModel.account_id == account_id)
        if search.strip():
            term = f"%{search.strip()}%"
            stmt = stmt.where(
                (TransactionModel.payee_text.ilike(term))
                | (TransactionModel.memo.ilike(term))
                | (TransactionModel.reference.ilike(term))
            )
        return list(self.session.scalars(stmt))

    def add(self, transaction: TransactionModel):
        self.session.add(transaction)
        self.session.flush()
        return transaction

    def reference_exists(self, account_id, reference):
        stmt = select(TransactionModel.id).where(
            TransactionModel.account_id == account_id,
            TransactionModel.reference == reference,
        )
        return self.session.scalar(stmt) is not None

    def duplicate_exists(self, account_id, tx_date, signed_minor, payee, memo):
        stmt = select(TransactionModel.id).where(
            TransactionModel.account_id == account_id,
            TransactionModel.transaction_date == tx_date,
            TransactionModel.signed_amount_minor == signed_minor,
            TransactionModel.payee_text == (payee or ""),
            TransactionModel.memo == (memo or ""),
        )
        return self.session.scalar(stmt) is not None
