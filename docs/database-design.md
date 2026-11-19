# Database design

## Tables

- `accounts`: account name, type, currency, opening balance in minor units.
- `categories`: hierarchical income/expense categories.
- `payees`: transaction counterparties.
- `transactions`: dated signed ledger entries, linked to accounts.
- `import_batches`: provenance and summary of each import.
- `transfers`: transfer grouping identifier is stored on both ledger entries.

## Relationships

- Account 1 -> many Transactions.
- Category 1 -> many Transactions.
- Payee 1 -> many Transactions.
- ImportBatch 1 -> many Transactions (optional provenance).

## Monetary storage

SQLite `REAL` is intentionally avoided. The database stores signed integer minor units.
For EUR, 1234 minor units represents €12.34. The MVP assumes 2 decimal places for
posting; currencies with other minor-unit conventions need a currency metadata upgrade.

## Balance

`opening_balance_minor + SUM(signed_amount_minor)` for an account. A transfer contributes
a negative amount to the source account and a positive amount to the destination.
