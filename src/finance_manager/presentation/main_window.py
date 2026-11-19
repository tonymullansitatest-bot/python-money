import csv
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QInputDialog
)
from sqlalchemy import select

from finance_manager.application.services import (
    AccountService, CategoryService, ImportService, ReportService,
    TransactionService, TransferService
)
from finance_manager.domain.enums import AccountType
from finance_manager.domain.money import from_minor_units
from finance_manager.infrastructure.models import AccountModel, CategoryModel
from finance_manager.infrastructure.qif import parse_qif


class FinanceMainWindow(QMainWindow):
    """Main window for navigating and managing personal finance data."""

    def __init__(self, session_factory):
        """Initialize the navigation shell and open the dashboard."""
        super().__init__()
        self.session_factory = session_factory
        self.setWindowTitle("Personal Finance Manager")
        self.resize(1100, 720)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)

        nav = QVBoxLayout()
        self.stack = QStackedWidget()
        outer.addLayout(nav, 1)
        outer.addWidget(self.stack, 5)

        for title, builder in [
            ("Dashboard", self.dashboard_page),
            ("Accounts", self.accounts_page),
            ("Transactions", self.transactions_page),
            ("Categories", self.categories_page),
            ("Reports", self.reports_page),
        ]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, b=builder: self.show_page(b))
            nav.addWidget(button)

        nav.addStretch()
        import_button = QPushButton("Import QIF")
        import_button.clicked.connect(self.import_qif)
        nav.addWidget(import_button)

        self.pages = {}
        self.show_page(self.dashboard_page)

    def show_page(self, builder):
        """Display a page, creating it on demand and refreshing it if supported."""
        key = builder.__name__
        if key not in self.pages:
            self.pages[key] = builder()
            self.stack.addWidget(self.pages[key])
        self.stack.setCurrentWidget(self.pages[key])
        refresh = getattr(self.pages[key], "refresh", None)
        if refresh:
            refresh()

    def dashboard_page(self):
        """Build the dashboard showing balances for each account."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("<h1>Financial Dashboard</h1>"))
        self.dashboard_summary = QLabel()
        self.dashboard_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.dashboard_summary)
        layout.addWidget(QLabel("Account balances"))
        self.dashboard_table = QTableWidget(0, 3)
        self.dashboard_table.setHorizontalHeaderLabels(["Account", "Type", "Balance"])
        self.dashboard_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.dashboard_table)

        def refresh():
            with self.session_factory() as session:
                accounts = AccountService(session).list_accounts()
                self.dashboard_table.setRowCount(len(accounts))
                for row, account in enumerate(accounts):
                    balance = from_minor_units(AccountService(session).balance(account.id))
                    for col, value in enumerate(
                        [account.name, account.account_type, f"{account.currency} {balance:,.2f}"]
                    ):
                        self.dashboard_table.setItem(row, col, QTableWidgetItem(str(value)))
                self.dashboard_summary.setText(
                    "<p>Balances are shown separately by account currency; different currencies "
                    "are not added together. Transfers are included in account balances but "
                    "excluded from income/expense reports.</p>"
                )
        page.refresh = refresh
        return page

    def accounts_page(self):
        """Build the account creation form and account listing."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("<h1>Accounts</h1>"))
        form = QFormLayout()
        name = QLineEdit()
        kind = QComboBox()
        kind.addItems([x.value for x in AccountType])
        opening = QLineEdit("0.00")
        currency = QLineEdit("EUR")
        form.addRow("Account name", name)
        form.addRow("Account type", kind)
        form.addRow("Opening balance", opening)
        form.addRow("Currency", currency)
        layout.addLayout(form)
        status = QLabel()
        layout.addWidget(status)
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["ID", "Name", "Type", "Currency"])
        layout.addWidget(table)

        def refresh():
            with self.session_factory() as session:
                accounts = AccountService(session).list_accounts()
                table.setRowCount(len(accounts))
                for row, item in enumerate(accounts):
                    for col, value in enumerate(
                        [item.id, item.name, item.account_type, item.currency]
                    ):
                        table.setItem(row, col, QTableWidgetItem(str(value)))

        def add():
            try:
                with self.session_factory() as session:
                    AccountService(session).create_account(
                        name.text(), kind.currentText(), opening.text(), currency.text()
                    )
                name.clear()
                status.setText("Account created.")
                refresh()
            except Exception as exc:
                QMessageBox.warning(page, "Could not create account", str(exc))

        button = QPushButton("Add account")
        button.clicked.connect(add)
        layout.addWidget(button)
        page.refresh = refresh
        refresh()
        return page

    def transactions_page(self):
        """Build the transaction entry form, search field, and transaction list."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("<h1>Transactions</h1>"))
        form = QFormLayout()
        account = QComboBox()
        tx_type = QComboBox()
        tx_type.addItems(["Expense", "Income"])
        tx_date = QDateEdit()
        tx_date.setCalendarPopup(True)
        tx_date.setDate(date.today())
        amount = QLineEdit()
        payee = QLineEdit()
        memo = QLineEdit()
        category = QComboBox()
        form.addRow("Account", account)
        form.addRow("Type", tx_type)
        form.addRow("Date", tx_date)
        form.addRow("Amount", amount)
        form.addRow("Payee", payee)
        form.addRow("Memo", memo)
        form.addRow("Category", category)
        layout.addLayout(form)
        search = QLineEdit()
        search.setPlaceholderText("Search payee, memo or reference")
        layout.addWidget(search)
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(["Date", "Type", "Payee", "Memo", "Amount", "Account"])
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        status = QLabel()
        layout.addWidget(status)

        def refresh():
            with self.session_factory() as session:
                accounts_list = AccountService(session).list_accounts()
                categories_list = CategoryService(session).list_categories()
                current_account = account.currentData()
                account.clear()
                for a in accounts_list:
                    account.addItem(f"{a.name} ({a.currency})", a.id)
                if current_account is not None:
                    idx = account.findData(current_account)
                    if idx >= 0:
                        account.setCurrentIndex(idx)
                current_category = category.currentData()
                category.clear()
                category.addItem("Uncategorised", None)
                for c in categories_list:
                    category.addItem(c.name, c.id)
                if current_category is not None:
                    idx = category.findData(current_category)
                    if idx >= 0:
                        category.setCurrentIndex(idx)
                txs = TransactionService(session).list_transactions(
                    search=search.text()
                )
                table.setRowCount(len(txs))
                for row, tx in enumerate(txs):
                    account_obj = session.get(AccountModel, tx.account_id)
                    vals = [
                        tx.transaction_date.isoformat(), tx.transaction_type,
                        tx.payee_text, tx.memo,
                        str(from_minor_units(tx.signed_amount_minor)),
                        account_obj.name if account_obj else ""
                    ]
                    for col, val in enumerate(vals):
                        table.setItem(row, col, QTableWidgetItem(str(val)))

        def add():
            try:
                if account.currentData() is None:
                    raise ValueError("Create an account first")
                with self.session_factory() as session:
                    TransactionService(session).add_transaction(
                        account.currentData(), tx_date.date().toPython(),
                        amount.text(), tx_type.currentText(), payee.text(),
                        memo.text(), category.currentData()
                    )
                amount.clear()
                status.setText("Transaction saved.")
                refresh()
            except Exception as exc:
                QMessageBox.warning(page, "Could not save transaction", str(exc))

        button = QPushButton("Add transaction")
        button.clicked.connect(add)
        search.textChanged.connect(refresh)
        layout.addWidget(button)
        page.refresh = refresh
        refresh()
        return page

    def categories_page(self):
        """Build the category creation form and category listing."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("<h1>Categories</h1>"))
        form = QFormLayout()
        name = QLineEdit()
        kind = QComboBox()
        kind.addItems(["Expense", "Income"])
        form.addRow("Name", name)
        form.addRow("Type", kind)
        layout.addLayout(form)
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["ID", "Name", "Type"])
        layout.addWidget(table)

        def refresh():
            with self.session_factory() as session:
                cats = CategoryService(session).list_categories()
                table.setRowCount(len(cats))
                for row, c in enumerate(cats):
                    for col, val in enumerate([c.id, c.name, c.kind]):
                        table.setItem(row, col, QTableWidgetItem(str(val)))

        def add():
            try:
                with self.session_factory() as session:
                    CategoryService(session).create_category(name.text(), kind.currentText())
                name.clear()
                refresh()
            except Exception as exc:
                QMessageBox.warning(page, "Could not create category", str(exc))

        button = QPushButton("Add category")
        button.clicked.connect(add)
        layout.addWidget(button)
        page.refresh = refresh
        refresh()
        return page

    def reports_page(self):
        """Build the date-range income and expense report page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("<h1>Income and Expenses</h1>"))
        start = QDateEdit()
        start.setCalendarPopup(True)
        start.setDate(date(date.today().year, 1, 1))
        end = QDateEdit()
        end.setCalendarPopup(True)
        end.setDate(date.today())
        form = QFormLayout()
        form.addRow("From", start)
        form.addRow("To", end)
        layout.addLayout(form)
        result = QLabel()
        layout.addWidget(result)

        def refresh():
            with self.session_factory() as session:
                data = ReportService(session).income_expense(
                    start.date().toPython(), end.date().toPython()
                )
            income = from_minor_units(data["income_minor"])
            expenses = from_minor_units(data["expenses_minor"])
            net = from_minor_units(data["net_minor"])
            result.setText(
                f"<h2>Income: EUR {income:,.2f}</h2>"
                f"<h2>Expenses: EUR {expenses:,.2f}</h2>"
                f"<h2>Net: EUR {net:,.2f}</h2>"
            )

        button = QPushButton("Generate report")
        button.clicked.connect(refresh)
        layout.addWidget(button)
        page.refresh = refresh
        refresh()
        return page

    def import_qif(self):
        """Import QIF transactions into a selected account after user confirmation."""
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select QIF file", "", "Quicken Interchange Format (*.qif);;All files (*)"
        )
        if not filename:
            return
        try:
            records = parse_qif(filename)
            if not records:
                raise ValueError("No QIF transactions were found")
            with self.session_factory() as session:
                accounts = AccountService(session).list_accounts()
                choices = [f"{a.id}: {a.name}" for a in accounts]
            if not choices:
                raise ValueError("Create a destination account before importing")
            selected, ok = QInputDialog.getItem(
                self, "Destination account", "Import these records into:", choices, 0, False
            )
            if not ok:
                return
            account_id = int(selected.split(":", 1)[0])
            preview = (
                f"File: {filename}\nRecords: {len(records)}\n"
                f"First date: {records[0]['date']}\n"
                f"Last date: {records[-1]['date']}\n\nCommit this import?"
            )
            answer = QMessageBox.question(self, "Confirm QIF import", preview)
            if answer != QMessageBox.Yes:
                return
            with self.session_factory() as session:
                result = ImportService(session).commit_qif(filename, account_id, records)
            QMessageBox.information(
                self, "Import complete",
                f"Imported: {result['imported']}\nSkipped duplicates: {result['skipped']}"
            )
            self.show_page(self.transactions_page)
        except Exception as exc:
            QMessageBox.critical(self, "QIF import failed", str(exc))
