from enum import Enum


class AccountType(str, Enum):
    CURRENT = "Current"
    SAVINGS = "Savings"
    CREDIT_CARD = "Credit Card"
    CASH = "Cash"
    LOAN = "Loan"
    OTHER = "Other"


class TransactionType(str, Enum):
    INCOME = "Income"
    EXPENSE = "Expense"
    TRANSFER = "Transfer"
