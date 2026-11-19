from pathlib import Path

from finance_manager.infrastructure.qif import parse_qif, parse_qif_date


def test_parse_qif(tmp_path: Path):
    qif = tmp_path / "sample.qif"
    qif.write_text(
        "!Type:Bank\nD01/15/2026\nT-12.34\nPExample Shop\nMWeekly shop\nLFood:Groceries\n^\n"
        "D01/20/2026\nT2500.00\nPSalary\n^\n",
        encoding="utf-8"
    )
    records = parse_qif(qif)
    assert len(records) == 2
    assert records[0]["payee"] == "Example Shop"
    assert str(records[0]["amount"]) == "-12.34"
    assert records[0]["category"] == "Food:Groceries"
    assert records[1]["date"].isoformat() == "2026-01-20"


def test_date_formats():
    assert parse_qif_date("15/01/2026").isoformat() == "2026-01-15"
