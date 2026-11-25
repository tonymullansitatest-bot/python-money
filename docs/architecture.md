# Architecture

## Goals

- Local-first Windows desktop finance application.
- Clear separation between presentation, application services, domain rules and
  infrastructure.
- Import adapters that normalize external file formats into internal records.
- Financial amounts stored exactly as integer minor units.
- Testable services independent of the PySide6 UI.

## Layers

```text
PySide6 Presentation
       |
       v
Application Services  ---- Import / Export adapters
       |
       v
Domain entities and rules
       |
       v
Repositories / SQLAlchemy
       |
       v
SQLite
```

### Presentation

`presentation/main_window.py` owns the main window and navigation. Each page is a
small QWidget. UI event handlers call application services; they do not issue SQL.

### Application

Services coordinate use cases:
- `AccountService`: create and list accounts.
- `PensionService`: record contributions, withdrawals and valuation adjustments.
- `CategoryService`: create and list categories.
- `TransactionService`: post, list and search transactions.
- `ScheduledTransactionService`: create monthly reminders, post due occurrences and
  advance their due dates.
- `TransferService`: post balanced transfer entries in one database transaction.
- `ImportService`: parse QIF, preview and commit imported records.
- `ReportService`: aggregate income and expenses.

### Domain

Domain enums and value conventions are independent of SQLAlchemy and Qt. Monetary
amounts use `Decimal` at application boundaries and integer minor units in storage.

### Infrastructure

SQLAlchemy models, database session factory, repositories, QIF parser and CSV exporter.
The optional AI assistant sends only manually entered text to OpenAI after confirmation;
it has no database access or tools for changing records.

## Important accounting conventions

- A transaction amount is a positive user-entered magnitude.
- The persisted `signed_amount_minor` is positive for income and negative for expense.
- Transfer debit and credit entries have opposite signs and share a transfer identifier.
- Transfers are excluded from income/expense totals.
- Pension accounts and their transactions are excluded from income/expense reporting;
  pension balances are displayed separately. Pension account types cannot be converted.
- Split transactions are a future extension; do not approximate splits by duplicating
  the parent transaction.
- Opening balance is stored on the account and is not an income/expense transaction.
- Scheduled transactions are reminders; posting one creates a normal income/expense
  transaction and advances the next due date in the same commit.

## Microsoft Money Plus Sunset migration

Phase 1: export each Money account to QIF, create a corresponding destination account,
then import and reconcile.

Phase 2: investigate `.mny` compatibility as an isolated spike. Native MNY parsing is
not part of this scaffold. The file format, file version, password protection, and
supported record types need empirical validation. Preserve the source file and never
write back to it.

## Security and recovery

The database currently uses the operating-system user profile directory and SQLite.
This is not database encryption. Restrict access through Windows account permissions,
use full-disk encryption, and make backups before importing. Manual backup uses SQLite's
online backup API. Restore validates a snapshot, checks schema compatibility, and creates
a safety backup before replacing the current database. Close other application instances
before restoring. Backups are unencrypted. Application-level encryption remains a future
release requirement.

## Suggested next architectural increments

1. Alembic-managed migrations (initial scaffold uses `create_all` for first-run ease).
2. Split transactions and reconciliation workflow.
3. Configurable CSV import mapping and OFX/QFX.
4. Audit log.
5. Native MNY compatibility investigation.
