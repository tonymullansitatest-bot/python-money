from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton

from finance_manager.application.services import AccountService, TransactionService
from finance_manager.infrastructure.database import build_session_factory
from finance_manager.presentation.main_window import FinanceMainWindow


def test_transaction_payee_autocomplete_refreshes_and_survives_reopening(
    session, monkeypatch
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    account = AccountService(session).create_account("Current")
    TransactionService(session).add_transaction(
        account.id, date.today(), "1", "Expense", "Example Shop"
    )
    factory = build_session_factory(session.get_bind())
    window = FinanceMainWindow(factory)
    window.show()
    window.show_page(window.transactions_page)
    app.processEvents()
    page = window.pages["transactions_page"]
    payee = page.findChild(QLineEdit, "transactionPayee")
    completer = payee.completer()
    completer.setCompletionPrefix("example")
    assert completer.completionCount() == 1
    assert completer.currentCompletion() == "Example Shop"
    payee.setFocus()
    QTest.keyClicks(payee, "exam")
    app.processEvents()
    assert completer.popup().isVisible()
    QTest.keyClick(completer.popup(), Qt.Key_Down)
    QTest.keyClick(completer.popup(), Qt.Key_Return)
    assert payee.text() == "Example Shop"

    page.findChild(QLineEdit, "transactionAmount").setText("2")
    payee.setText("Another Shop")
    page.findChild(QPushButton, "addTransaction").click()
    completer.setCompletionPrefix("another")
    assert completer.currentCompletion() == "Another Shop"

    window.close()
    window = FinanceMainWindow(factory)
    window.show_page(window.transactions_page)
    payee = window.pages["transactions_page"].findChild(QLineEdit, "transactionPayee")
    completer = payee.completer()
    completer.setCompletionPrefix("ANOTHER")
    assert completer.completionCount() == 1
    assert completer.currentCompletion() == "Another Shop"
    payee.setFocus()
    QTest.keyClicks(payee, "new payee")
    assert payee.text() == "new payee"
    assert completer.caseSensitivity() == Qt.CaseInsensitive
    window.close()
    app.processEvents()
