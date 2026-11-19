# Personal Finance Manager

A local-first Windows desktop personal finance application built with Python, PySide6,
SQLAlchemy and SQLite. The initial MVP supports accounts, categories, payees,
transactions, account transfers, a dashboard, CSV export and QIF import.

## Status

This is an initial working scaffold, not yet a complete Microsoft Money replacement.
Money Plus Sunset native `.mny` parsing is **not implemented**. Use Microsoft Money's
export facilities to export account data to QIF, then import those files here. Keep
your original `.mny` file and a separate backup untouched.

## Requirements

- Windows 10/11 (other platforms may work)
- Python 3.11 or later
- Internet access for the initial package installation only

## Setup (PowerShell)

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev,reports]"
```

If PowerShell blocks activation, use:
```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev,reports]"
.venv\Scripts\python.exe -m finance_manager.main
```

## Run

```powershell
finance-manager
```

Or:
```powershell
python -m finance_manager.main
```

The database is created in the user's application data directory, not inside the
source repository. On Windows this is normally `%LOCALAPPDATA%\PersonalFinanceManager`.

## Tests and quality

```powershell
pytest
ruff check .
ruff format .
```

## First-run workflow

1. Start the application.
2. Open **Accounts** and create a current or savings account with an opening balance.
3. Open **Categories** and add categories such as Salary, Groceries and Utilities.
4. Open **Transactions** to enter income and expenses.
5. Use **Import QIF** to import an exported Microsoft Money account file.
6. Review the dashboard and export transactions to CSV.

## QIF import notes

QIF is commonly exported one account at a time. Create or select the destination account
before importing. The importer supports common bank-style records (`D`, `T`, `P`, `M`,
`L`, `N`, `C`) and common date formats. QIF variants differ; inspect the preview and
reconcile account balances and transaction counts after each import.

The first implementation intentionally does not silently create categories or payees
during import. Unknown categories are retained as text in the import preview and mapped
to a default "Uncategorised" category when committed. Review imported data carefully.

## Financial correctness

- Amounts are represented using Python `Decimal`.
- Amounts are persisted as integer minor units (cents) in SQLite.
- Expenses are negative ledger entries; income is positive.
- Transfers create linked debit and credit entries and are excluded from income/expense
  reporting.
- This MVP assumes two-decimal currencies for posting. Currency metadata is stored,
  but full multi-currency conversion is not yet implemented.
- Do not use this software as a tax, investment or regulated financial reporting system.

## Project structure

See `docs/architecture.md` and `docs/database-design.md`.
