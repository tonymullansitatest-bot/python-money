from datetime import date

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLineEdit,
    QPushButton,
    QTableWidget,
)

from finance_manager.application.services import (
    AccountService,
    PensionService,
    TransferService,
)
from finance_manager.domain.enums import AccountType
from finance_manager.infrastructure.database import build_session_factory
from finance_manager.presentation.main_window import FinanceMainWindow


def test_pension_page_records_activity_and_shows_transfer(session, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    accounts = AccountService(session)
    current = accounts.create_account("Current")
    pension = accounts.create_account("Pension", AccountType.PENSION.value)
    TransferService(session).create_transfer(current.id, pension.id, "10", date.today())

    window = FinanceMainWindow(build_session_factory(session.get_bind()))
    window.show_page(window.pensions_page)
    page = window.pages["pensions_page"]
    assert page.findChild(QComboBox, "pensionAccount").currentData() == pension.id
    table = page.findChild(QTableWidget, "pensionActivity")
    assert table.rowCount() == 1
    assert table.item(0, 1).text() == "Transfer"
    page.findChild(QComboBox, "pensionActivityType").setCurrentText("Valuation gain")
    page.findChild(QLineEdit, "pensionActivityAmount").setText("5")
    page.findChild(QPushButton, "addPensionActivity").click()
    assert table.rowCount() == 2
    session.expire_all()
    assert accounts.balance(pension.id) == 1500

    window.show_page(window.transactions_page)
    transactions = window.pages["transactions_page"]
    assert transactions.findChild(QComboBox).count() == 1
    window.close()
    app.processEvents()


def test_transactions_page_does_not_show_pension_when_no_regular_accounts(
    session, monkeypatch
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    pension = AccountService(session).create_account(
        "Pension", AccountType.PENSION.value
    )
    PensionService(session).add_activity(pension.id, date.today(), "10", "Contribution")
    window = FinanceMainWindow(build_session_factory(session.get_bind()))
    window.show_page(window.transactions_page)
    page = window.pages["transactions_page"]
    assert page.findChild(QComboBox).count() == 0
    assert page.findChild(QTableWidget).rowCount() == 0
    window.close()
    app.processEvents()
