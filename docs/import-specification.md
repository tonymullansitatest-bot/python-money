# Import specification: Money Plus Sunset

## Current support

QIF (`.qif`) import is implemented for common bank account exports. Export from Money
Plus Sunset one account at a time. Create the matching account in the app first.

## Parser behaviour

- `D`: transaction date
- `T`: amount
- `P`: payee
- `M`: memo
- `L`: category (subcategories separated by `:`)
- `N`: reference / check number
- `C`: cleared status
- `^`: end of record

Unknown QIF tags are ignored. Unsupported or malformed dates and amounts are reported
as errors. The importer returns preview records and does not write to the database.

## Commit

The UI asks for an existing destination account. Imported records are committed in a
single database transaction. Category names are matched case-insensitively; unmatched
categories use/create `Uncategorised`. Duplicate detection currently uses account,
date, signed amount, payee and memo. Review possible duplicates before importing.

## Native MNY

Not supported in this release. Do not rename `.mny` to `.qif` or attempt to parse it as
text. Native support requires a separate compatibility investigation and test corpus.

## Date ambiguity

QIF date strings can be locale-dependent. Dates such as `03/04/2026` are ambiguous
without knowing the export locale. Before importing a real Money file, confirm the date
format in the source export and reconcile several known transactions. The current parser
tries common US formats before day-first formats; this ordering will be made configurable
in the import wizard before a production migration.
