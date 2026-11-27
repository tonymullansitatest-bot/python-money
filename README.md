# Personal Finance Manager

A local-first Windows desktop personal finance application built with Python, PySide6,
SQLAlchemy and SQLite. The initial MVP supports accounts, categories, payees,
transactions, monthly scheduled-transaction reminders, account transfers, a dashboard,
CSV export and QIF import. Pension accounts are managed separately from ordinary
accounts and income/expense reporting.

## Status

This is an initial working scaffold, not yet a complete Microsoft Money replacement.
Money Plus Sunset native `.mny` parsing is **not implemented**. Use Microsoft Money's
export facilities to export account data to QIF, then import those files here. Keep
your original `.mny` file and a separate backup untouched.

## Requirements

- Windows 10/11 (other platforms may work)
- Python 3.11 or later
- Internet access for the initial package installation and optional AI requests

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

## Backup and restore

Use **Back up database** to save a consistent SQLite snapshot to a new file. Choose a
secure location, preferably on a separate device; backups contain unencrypted financial
data. Existing files are never overwritten.

To restore, close other instances of the application and select **Restore database**.
After confirmation, the selected backup replaces all current financial data and any
unfinished forms are discarded. The app checks database integrity, references and
schema compatibility first, and saves a uniquely named `pre-restore` safety backup in
the database directory before replacing data. Backups must match the current database
schema; a backup from a different version may not be compatible. Backups do not include
application preferences such as the theme. Test your backups periodically.

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
5. Use **Scheduled** to create monthly bill reminders. Due items appear on the dashboard
   and are posted only when you select them.
6. Use **Import QIF** to import an exported Microsoft Money account file.
7. Review the dashboard and export transactions to CSV.

When entering or editing a transaction, start typing a payee to see suggestions from
saved and previously recorded payees. New payees are saved with the transaction and
remain available even if it is later deleted. Suggestions are local to the database.

## Pension accounts

Use **Pensions** to create and manage pension accounts, view individual balances and
active totals by currency, and record contributions, withdrawals, valuation gains and
valuation losses. Enter positive amounts; the activity type determines the direction.
Use **Transfers** when money moves between a pension and another account so both
balances are updated without treating the movement as income or expense. Use a
standalone contribution or withdrawal for activity outside the tracked accounts.
To correct an activity, delete it and enter it again; deleting a transfer removes both
legs. Archived pensions remain visible but cannot receive new activity.

Pension balances and activity are excluded from the ordinary dashboard, income,
expense and net savings reports, including imported pension transactions. Pension
accounts cannot be converted to or from another account type. Valuation changes
are manual adjustments, not automatic investment pricing or tax calculations.

## AI assistant

The **AI Assistant** answers general finance questions or summarises manually entered,
non-sensitive text. It cannot access or change your accounts and does not automatically
send database records. Do not enter transaction details, account identifiers, names,
credentials or other personal or confidential information. Confirm each request before
it is sent to OpenAI; the app does not automatically detect sensitive text. Requests
require internet access and may incur API charges.

Set `OPENAI_API_KEY` in the environment before launching the application. The default
model is `gpt-6.1-terra`; optionally set `OPENAI_MODEL` to a model available to your API
account. The app does not save conversations and sets `store=False` on requests, but
OpenAI's [data retention policy](https://developers.openai.com/api/docs/guides/your-data)
may still apply. Responses can be inaccurate and are not financial, investment or tax
advice.

## Scheduled transactions

Scheduled transactions are monthly reminders, not automatic payments or ledger entries.
When a reminder is due, review it and choose **Post due transaction** to add it to the
account. The next due date advances one month; if a date falls beyond a month's last
day, it uses that month's last day while retaining the original day for later months.
Overdue months are posted one at a time. Reminders can be paused and resumed.

For a scheduled transfer, choose the source and destination accounts and enter the
amount in the source currency. Posting creates both transfer entries together and
excludes them from income and expense reports. For different currencies, enter the
exchange rate each time you post. Both accounts must be active. For a loan payment,
schedule the principal as a transfer to the loan account and record interest and fees
separately as expenses.

The Dashboard's **Account balances** table also shows a dated two-week forecast.
This adds every unposted occurrence of active scheduled income, expenses and
same-currency transfers due through 14 days from today, including overdue months,
to the current ledger balance. Both transfer legs are included, even when the other
account is a pension. Paused reminders and activity involving inactive accounts are
excluded. Cross-currency scheduled transfers are excluded from both accounts with a
visible forecast warning because their exchange rate is only entered when posting.
Forecasts are estimates only: they do not post transactions or advance reminder dates,
and are independent of the Dashboard's reporting period and currency filters.

Existing databases gain a scheduled-transfer table when the application starts.
Backups created before this schema change cannot be restored directly into the updated
database; keep them separately and create a fresh backup after upgrading.

## QIF import notes

QIF is commonly exported one account at a time. Create or select the destination account
before importing. The importer supports common bank-style records (`D`, `T`, `P`, `M`,
`L`, `N`, `C`) and common date formats. QIF variants differ; inspect the preview and
reconcile account balances and transaction counts after each import.

Imported payees are saved for transaction suggestions. Unknown categories are retained
as text in the import preview and mapped to a default "Uncategorised" category when
committed. Review imported data carefully.

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
