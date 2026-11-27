from datetime import date, timedelta

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QInputDialog,
    QLabel,
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


def test_dashboard_shows_two_week_forecast_and_cross_currency_warning(
    session, monkeypatch
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    accounts = AccountService(session)
    current = accounts.create_account("Current", opening_balance="100")
    savings = accounts.create_account("Savings")
    dollar = accounts.create_account("Dollar", currency="USD")
    schedules = ScheduledTransactionService(session)
    horizon = date.today() + timedelta(days=14)
    income = schedules.create_schedule(
        "Income", current.id, "50", "Income", horizon
    )
    schedules.create_schedule(
        "Transfer", current.id, "20", "Transfer", horizon,
        destination_id=savings.id,
    )
    schedules.create_schedule(
        "FX", current.id, "30", "Transfer", horizon,
        destination_id=dollar.id,
    )
    schedules.create_schedule(
        "Outside forecast", current.id, "999", "Expense",
        horizon + timedelta(days=1),
    )
    window = FinanceMainWindow(build_session_factory(session.get_bind()))
    try:
        page = window.pages["dashboard_page"]
        table = page.findChild(QTableWidget, "dashboardBalances")
        assert table.horizontalHeaderItem(3).text() == (
            f"Forecast ({horizon:%d %b %Y})"
        )
        values = {
            table.item(row, 0).text(): (
                table.item(row, 2).text(), table.item(row, 3).text()
            )
            for row in range(table.rowCount())
        }
        assert values == {
            "Current": ("EUR 100.00", "EUR 130.00"),
            "Savings": ("EUR 0.00", "EUR 20.00"),
            "Dollar": ("USD 0.00", "USD 0.00"),
        }
        assert "FX: cross-currency transfer excluded" in page.findChild(
            QLabel, "forecastNote"
        ).text()
        schedules.post_due(income.id, horizon)
        window.show_page(window.dashboard_page)
        assert table.item(0, 2).text() == "EUR 150.00"
        assert table.item(0, 3).text() == "EUR 130.00"
    finally:
        window.close()
        app.processEvents()
