from datetime import date

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QInputDialog,
    QLineEdit,
    QPushButton,
    QTableWidget,
)

from finance_manager.application.services import (
    AccountService,
    ScheduledTransactionService,
)
from finance_manager.infrastructure.database import build_session_factory
from finance_manager.presentation.main_window import FinanceMainWindow


def test_scheduled_transfer_ui_requests_rate_when_posted(session, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    accounts = AccountService(session)
    source = accounts.create_account("Euro")
    target = accounts.create_account("Dollar", currency="USD")
    window = FinanceMainWindow(build_session_factory(session.get_bind()))
    window.show_page(window.scheduled_transactions_page)
    page = window.pages["scheduled_transactions_page"]
    page.findChild(QComboBox, "scheduleType").setCurrentText("Transfer")
    source_box = page.findChild(QComboBox, "scheduleAccount")
    destination_box = page.findChild(QComboBox, "scheduleDestination")
    source_box.setCurrentIndex(source_box.findData(source.id))
    destination_box.setCurrentIndex(destination_box.findData(target.id))
    page.findChild(QLineEdit, "scheduleName").setText("Transfer")
    page.findChild(QLineEdit, "scheduleAmount").setText("100")
    page.findChild(QPushButton, "addSchedule").click()

    table = page.findChild(QTableWidget, "scheduleTable")
    assert table.rowCount() == 1
    assert "Euro" in table.item(0, 1).text()
    assert "Dollar" in table.item(0, 1).text()
    table.selectRow(0)
    post = page.findChild(QPushButton, "postSchedule")
    assert post.isEnabled()
    monkeypatch.setattr(QInputDialog, "getText", lambda *args: ("", False))
    post.click()
    session.expire_all()
    assert accounts.balance(source.id) == 0
    assert (
        ScheduledTransactionService(session).list_schedules()[0].next_due_date
        == date.today()
    )
    monkeypatch.setattr(QInputDialog, "getText", lambda *args: ("1.2", True))
    post.click()
    session.expire_all()
    assert (accounts.balance(source.id), accounts.balance(target.id)) == (-10000, 12000)
    window.close()
    app.processEvents()
