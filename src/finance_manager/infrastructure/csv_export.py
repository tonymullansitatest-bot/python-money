import csv
from pathlib import Path

from finance_manager.domain.money import from_minor_units


def export_transactions_csv(transactions, path: str | Path):
    with Path(path).open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Date", "Account", "Type", "Payee", "Memo",
                         "Amount", "Reference", "Category"])
        for tx in transactions:
            writer.writerow([
                tx.transaction_date.isoformat(), tx.account.name,
                tx.transaction_type, tx.payee_text, tx.memo,
                str(from_minor_units(tx.signed_amount_minor)),
                tx.reference, tx.category.name if tx.category else ""
            ])
