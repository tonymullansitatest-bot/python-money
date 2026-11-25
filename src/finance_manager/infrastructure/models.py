from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finance_manager.infrastructure.database import Base


class AccountModel(Base):
    """A financial account and its opening balance and settings."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_type: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    opening_balance_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    transactions: Mapped[list["TransactionModel"]] = relationship(
        back_populates="account"
    )


class CategoryModel(Base):
    """A transaction category that may be nested under a parent category."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), default="Expense", nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    parent: Mapped["CategoryModel | None"] = relationship(
        remote_side="CategoryModel.id", back_populates="children"
    )
    children: Mapped[list["CategoryModel"]] = relationship(back_populates="parent")


class PayeeModel(Base):
    """A reusable payee name."""

    __tablename__ = "payees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)


class ImportBatchModel(Base):
    """Metadata and counts for a file import operation."""

    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(260), nullable=False)
    file_format: Mapped[str] = mapped_column(String(20), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    imported_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class TransactionModel(Base):
    """A posted transaction associated with an account."""

    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    signed_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(15), nullable=False)
    payee_text: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    memo: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reference: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True
    )
    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    transfer_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    account: Mapped[AccountModel] = relationship(back_populates="transactions")
    category: Mapped[CategoryModel | None] = relationship()


class ScheduledTransactionModel(Base):
    """A recurring transaction template with its next due date."""

    __tablename__ = "scheduled_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True
    )
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(10), nullable=False)
    payee_text: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    memo: Mapped[str] = mapped_column(Text, default="", nullable=False)
    next_due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    due_day: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
