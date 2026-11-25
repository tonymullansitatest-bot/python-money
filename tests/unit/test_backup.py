import sqlite3
from contextlib import closing

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from finance_manager.application.services import (
    AccountService,
    ScheduledTransactionService,
)
from finance_manager.infrastructure.backup import BackupError, BackupService
from finance_manager.infrastructure.database import (
    build_engine,
    build_session_factory,
    initialize_database,
)
from finance_manager.presentation.main_window import FinanceMainWindow


@pytest.fixture
def database(tmp_path):
    engine = build_engine(f"sqlite:///{(tmp_path / 'current.db').as_posix()}")
    initialize_database(engine)
    factory = build_session_factory(engine)
    yield engine, factory
    engine.dispose()


def add_account(factory, name):
    with factory() as session:
        AccountService(session).create_account(name)


def account_names(factory):
    with factory() as session:
        return [account.name for account in AccountService(session).list_accounts()]


def test_existing_database_gains_transfer_table_without_losing_reminders(database):
    from datetime import date

    engine, factory = database
    with factory() as session:
        account = AccountService(session).create_account("Current")
        ScheduledTransactionService(session).create_schedule(
            "Bill", account.id, "10", "Expense", date(2026, 1, 1)
        )
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE scheduled_transfers")
    initialize_database(engine)
    with factory() as session:
        schedules = ScheduledTransactionService(session).list_schedules()
        assert len(schedules) == 1
        assert schedules[0].name == "Bill"
        assert schedules[0].transfer is None


def test_backup_restore_and_safety_backup_include_wal_data(database, tmp_path):
    engine, factory = database
    service = BackupService(engine)
    with closing(sqlite3.connect(service.database)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    add_account(factory, "Before backup")
    backup = tmp_path / "backup.db"
    service.create_backup(backup)
    add_account(factory, "After backup")

    safety = service.restore(backup)
    assert account_names(factory) == ["Before backup"]
    with closing(sqlite3.connect(safety)) as connection:
        rows = connection.execute("SELECT name FROM accounts ORDER BY id").fetchall()
        assert rows == [
            ("Before backup",),
            ("After backup",),
        ]
    with closing(sqlite3.connect(backup)) as connection:
        assert connection.execute("SELECT name FROM accounts").fetchall() == [
            ("Before backup",)
        ]


def test_rejects_existing_output_and_active_database(database, tmp_path):
    engine, factory = database
    service = BackupService(engine)
    add_account(factory, "Kept")
    existing = tmp_path / "existing.db"
    existing.write_bytes(b"keep")
    with pytest.raises(BackupError, match="already exists"):
        service.create_backup(existing)
    with pytest.raises(BackupError, match="active database"):
        service.create_backup(service.database)
    with pytest.raises(BackupError, match="active database"):
        service.restore(service.database)
    assert existing.read_bytes() == b"keep"
    assert account_names(factory) == ["Kept"]


def test_invalid_or_incompatible_backup_does_not_change_current_database(
    database, tmp_path
):
    engine, factory = database
    service = BackupService(engine)
    add_account(factory, "Kept")
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a database")
    with pytest.raises(sqlite3.DatabaseError):
        service.restore(bad)
    other = tmp_path / "other.db"
    with closing(sqlite3.connect(other)) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER)")
    with pytest.raises(BackupError, match="incompatible"):
        service.restore(other)
    assert account_names(factory) == ["Kept"]
    assert not list(tmp_path.glob("*-pre-restore-*.db"))


def test_restore_refuses_foreign_key_corruption(database, tmp_path):
    engine, factory = database
    service = BackupService(engine)
    backup = tmp_path / "backup.db"
    service.create_backup(backup)
    with closing(sqlite3.connect(backup)) as connection:
        connection.execute(
            "INSERT INTO categories (name, kind, parent_id, is_active) "
            "VALUES ('bad', 'Expense', 999, 1)"
        )
        connection.commit()
    with pytest.raises(BackupError, match="invalid database references"):
        service.restore(backup)
    assert account_names(factory) == []


def test_restore_failure_reports_and_preserves_safety_backup(
    database, tmp_path, monkeypatch
):
    engine, factory = database
    service = BackupService(engine)
    add_account(factory, "Before backup")
    backup = tmp_path / "backup.db"
    service.create_backup(backup)
    add_account(factory, "After backup")
    copy = service._copy
    calls = 0

    def fail_restore(source, destination):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise sqlite3.OperationalError("database is locked")
        copy(source, destination)

    monkeypatch.setattr(service, "_copy", fail_restore)
    with pytest.raises(BackupError, match="safety backup"):
        service.restore(backup)
    safety, = tmp_path.glob("*-pre-restore-*.db")
    with closing(sqlite3.connect(safety)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM accounts").fetchone() == (2,)
    assert account_names(factory) == ["After backup", "Before backup"]


def test_backup_button_creates_file(database, tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    engine, factory = database
    add_account(factory, "Saved")
    backup = tmp_path / "backup.db"
    window = FinanceMainWindow(factory)
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(backup), "")
    )
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args))
    window.backup_database()
    with closing(sqlite3.connect(backup)) as connection:
        rows = connection.execute("SELECT name FROM accounts").fetchall()
        assert rows == [("Saved",)]
    assert "Backup complete" in messages[0]
    window.close()
    app.processEvents()


def test_backup_failure_is_shown_in_ui(database, tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    _, factory = database
    existing = tmp_path / "existing.db"
    existing.write_bytes(b"keep")
    window = FinanceMainWindow(factory)
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(existing), "")
    )
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args))
    window.backup_database()
    assert "already exists" in errors[0][2]
    assert existing.read_bytes() == b"keep"
    window.close()
    app.processEvents()


def test_restore_confirmation_and_ui_refresh(database, tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    engine, factory = database
    add_account(factory, "Before backup")
    backup = tmp_path / "backup.db"
    BackupService(engine).create_backup(backup)
    add_account(factory, "After backup")
    window = FinanceMainWindow(factory)
    window.show_page(window.accounts_page)
    old_page = window.pages["accounts_page"]
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(backup), ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.No)
    window.restore_database()
    assert account_names(factory) == ["After backup", "Before backup"]
    assert window.pages["accounts_page"] is old_page

    messages = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args))
    window.restore_database()
    assert account_names(factory) == ["Before backup"]
    assert "accounts_page" not in window.pages
    assert window.stack.currentWidget() is window.pages["dashboard_page"]
    assert "pre-restore" in messages[0][2]
    window.close()
    app.processEvents()
