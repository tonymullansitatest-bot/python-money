import csv
from datetime import date
from decimal import Decimal

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QPieSeries,
    QValueAxis,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from finance_manager.application.services import (
    AccountService,
    CategoryService,
    ImportService,
    PensionService,
    ReportService,
    ScheduledTransactionService,
    TransactionService,
    TransferService,
)
from finance_manager.domain.enums import AccountType
from finance_manager.domain.money import from_minor_units, to_minor_units
from finance_manager.infrastructure.csv_export import export_transactions_csv
from finance_manager.infrastructure.models import (
    AccountModel,
    CategoryModel,
    TransactionModel,
)
from finance_manager.infrastructure.qif import parse_qif
from finance_manager.infrastructure.revolut import parse_revolut_csv
from finance_manager.presentation.ai_page import AIPage
from finance_manager.presentation.themes import (
    apply_theme,
    available_themes,
    chart_colors,
    saved_theme,
)

_PIE_COLORS = (
    "#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6",
    "#94a3b8",
)


class FinanceMainWindow(QMainWindow):
    """Main window for navigating and managing personal finance data."""

    @staticmethod
    def _title(text):
        """Create a page heading that themes can target as #pageTitle."""
        label = QLabel(text)
        label.setObjectName("pageTitle")
        return label

    @staticmethod
    def _named(label, name):
        label.setObjectName(name)
        return label

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
            ("Pensions", self.pensions_page),
            ("Transactions", self.transactions_page),
            ("Scheduled", self.scheduled_transactions_page),
            ("Transfers", self.transfers_page),
            ("Categories", self.categories_page),
            ("Reports", self.reports_page),
            ("AI Assistant", self.ai_page),
        ]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, b=builder: self.show_page(b))
            nav.addWidget(button)

        nav.addStretch()
        nav.addWidget(QLabel("Theme"))
        self.theme_box = QComboBox()
        self.theme_box.addItems(list(available_themes()))
        self.theme_box.setCurrentText(saved_theme())
        self.theme_box.activated.connect(self._change_theme)
        nav.addWidget(self.theme_box)
        import_button = QPushButton("Import QIF")
        import_button.clicked.connect(self.import_qif)
        nav.addWidget(import_button)
        revolut_button = QPushButton("Import Revolut CSV")
        revolut_button.clicked.connect(self.import_revolut)
        nav.addWidget(revolut_button)

        self.pages = {}
        self.show_page(self.dashboard_page)

    def _change_theme(self, _index=None):
        """Apply the chosen theme and redraw charts, which take their colours from it."""
        apply_theme(self.theme_box.currentText())
        dashboard = self.pages.get("dashboard_page")
        if dashboard is not None:
            dashboard.refresh()

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

    def ai_page(self):
        return AIPage()

    def dashboard_page(self):
        """Build the dashboard: overview, monthly chart, spending pie and balances."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self._title("Financial Dashboard"))

        controls = QHBoxLayout()
        period = QComboBox()
        period.addItems(["Last 12 months", "This year", "Last year", "All time"])
        currency = QComboBox()
        controls.addWidget(QLabel("Period"))
        controls.addWidget(period)
        controls.addWidget(QLabel("Currency"))
        controls.addWidget(currency)
        controls.addStretch()
        layout.addLayout(controls)

        cards = QHBoxLayout()
        card_values = {}
        for key, caption in (
            ("income", "Total income"), ("expenses", "Total expenses"),
            ("net", "Net savings"),
        ):
            card = QFrame()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            card_layout.addWidget(self._named(QLabel(caption), "noteLabel"))
            value = QLabel("-")
            value.setObjectName("cardValue")
            value.setProperty("kind", key)
            card_values[key] = value
            card_layout.addWidget(value)
            cards.addWidget(card)
        layout.addLayout(cards)
        scheduled_reminder = QPushButton()
        scheduled_reminder.clicked.connect(
            lambda: self.show_page(self.scheduled_transactions_page)
        )
        layout.addWidget(scheduled_reminder)

        charts = QHBoxLayout()
        bar_view = QChartView()
        pie_view = QChartView()
        for view in (bar_view, pie_view):
            view.setRenderHint(QPainter.Antialiasing)
            view.setMinimumHeight(240)
            charts.addWidget(view)
        layout.addLayout(charts, 1)

        layout.addWidget(self._named(QLabel("Account balances"), "sectionLabel"))
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Account", "Type", "Balance"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setMaximumHeight(150)
        layout.addWidget(table)
        note = self._named(QLabel(
            "Charts and totals cover one currency at a time and exclude transfers "
            "and pension activity. "
            "Balances are shown per account currency."
        ), "noteLabel")
        note.setWordWrap(True)
        layout.addWidget(note)

        def date_range():
            today = date.today()
            choice = period.currentText()
            if choice == "This year":
                return date(today.year, 1, 1), today, "month"
            if choice == "Last year":
                return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), "month"
            if choice == "All time":
                return date(1900, 1, 1), date(9999, 12, 31), "year"
            year, month = today.year, today.month - 11
            if month < 1:
                year, month = year - 1, month + 12
            return date(year, month, 1), today, "month"

        def style_chart(chart, colors, title):
            chart.setTitle(title)
            chart.setBackgroundBrush(QColor(colors["input_bg"]))
            chart.setTitleBrush(QColor(colors["fg"]))
            chart.legend().setLabelColor(QColor(colors["fg"]))
            chart.setBackgroundRoundness(8)

        def build_bar(monthly, cur, colors):
            chart = QChart()
            income_set = QBarSet("Income")
            expense_set = QBarSet("Expenses")
            income_set.setColor(QColor(colors["positive"]))
            expense_set.setColor(QColor(colors["negative"]))
            labels = []
            top = 0.0
            for label, income, expenses in monthly:
                labels.append(label)
                income_set.append(float(from_minor_units(income)))
                expense_set.append(float(from_minor_units(expenses)))
                top = max(top, float(from_minor_units(max(income, expenses))))
            series = QBarSeries()
            series.append(income_set)
            series.append(expense_set)
            chart.addSeries(series)
            axis_x = QBarCategoryAxis()
            axis_x.append(labels)
            axis_y = QValueAxis()
            axis_y.setRange(0, top * 1.1 if top else 1)
            axis_y.setLabelFormat("%.0f")
            for axis in (axis_x, axis_y):
                axis.setLabelsColor(QColor(colors["fg"]))
                axis.setGridLineColor(QColor(colors["border"]))
            chart.addAxis(axis_x, Qt.AlignBottom)
            chart.addAxis(axis_y, Qt.AlignLeft)
            series.attachAxis(axis_x)
            series.attachAxis(axis_y)
            style_chart(chart, colors, f"Income vs expenses ({cur})")
            return chart

        def build_pie(categories, cur, colors):
            chart = QChart()
            spending = sorted(
                ((c["category"], c["expenses_minor"]) for c in categories
                 if c["currency"] == cur and c["expenses_minor"] > 0),
                key=lambda item: item[1], reverse=True
            )
            if len(spending) > 8:
                other = sum(amount for _, amount in spending[7:])
                spending = spending[:7] + [("Other", other)]
            total = sum(amount for _, amount in spending)
            series = QPieSeries()
            for index, (name, amount) in enumerate(spending):
                pie_slice = series.append(name, float(from_minor_units(amount)))
                pie_slice.setColor(QColor(_PIE_COLORS[index % len(_PIE_COLORS)]))
                pie_slice.setLabel(f"{name} {amount * 100 / total:.0f}%")
                pie_slice.setLabelColor(QColor(colors["fg"]))
                pie_slice.setLabelVisible(len(spending) <= 8)
            chart.addSeries(series)
            style_chart(chart, colors, f"Spending by category ({cur})")
            if not spending:
                chart.setTitle(f"Spending by category ({cur}) - no spending in this period")
            chart.legend().setAlignment(Qt.AlignRight)
            return chart

        def refresh():
            colors = chart_colors()
            with self.session_factory() as session:
                accounts = [
                    a for a in AccountService(session).list_accounts()
                    if a.account_type != AccountType.PENSION.value
                ]
                due_schedules = ScheduledTransactionService(session).due_schedules()
                currencies = sorted({a.currency for a in accounts})
                chosen = currency.currentText()
                currency.blockSignals(True)
                currency.clear()
                currency.addItems(currencies)
                if chosen in currencies:
                    currency.setCurrentText(chosen)
                currency.blockSignals(False)
                cur = currency.currentText()

                table.setRowCount(0)
                active = [a for a in accounts if a.is_active]
                table.setRowCount(len(active))
                for row, item in enumerate(active):
                    balance = from_minor_units(AccountService(session).balance(item.id))
                    for col, value in enumerate(
                        [item.name, item.account_type, f"{item.currency} {balance:,.2f}"]
                    ):
                        table.setItem(row, col, QTableWidgetItem(str(value)))

                start, end, by = date_range()
                service = ReportService(session)
                totals = service.income_expense(start, end).get(cur, {})
                monthly = service.monthly_totals(start, end, cur, by=by)
                categories = service.category_breakdown(start, end)

            due_count = len(due_schedules)
            if due_count == 1:
                scheduled_reminder.setText(
                    "1 scheduled transaction is due. Review it"
                )
            elif due_count:
                scheduled_reminder.setText(
                    f"{due_count} scheduled transactions are due. Review them"
                )
            else:
                scheduled_reminder.setText("No scheduled transactions due")
            totals_key = {
                "income": "income_minor", "expenses": "expenses_minor", "net": "net_minor"
            }
            for key, label in card_values.items():
                minor = totals.get(totals_key[key], 0)
                label.setText(f"{cur} {from_minor_units(minor):,.2f}" if cur else "-")
            bar_view.setChart(build_bar(monthly, cur, colors))
            pie_view.setChart(build_pie(categories, cur, colors))

        period.activated.connect(refresh)
        currency.activated.connect(refresh)
        page.refresh = refresh
        return page

    def pensions_page(self):
        return self.accounts_page(pension=True)

    def accounts_page(self, pension=False):
        """Build the account creation form and account listing."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self._title("Pensions" if pension else "Accounts"))
        form = QFormLayout()
        name = QLineEdit()
        kind = QComboBox()
        kind.addItems([
            x.value for x in AccountType
            if (x == AccountType.PENSION) == pension
        ])
        opening = QLineEdit("0.00")
        currency = QLineEdit("EUR")
        form.addRow("Account name", name)
        if not pension:
            form.addRow("Account type", kind)
        form.addRow("Opening balance", opening)
        form.addRow("Currency", currency)
        layout.addLayout(form)
        status = self._named(QLabel(), "statusLabel")
        layout.addWidget(status)
        table = QTableWidget(0, 6 if pension else 5)
        headers = ["ID", "Name", "Type", "Currency", "Status"]
        if pension:
            headers.append("Balance")
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(table)
        row_buttons = QHBoxLayout()
        edit_button = QPushButton("Edit selected")
        archive_button = QPushButton("Archive selected")
        delete_button = QPushButton("Delete selected")
        for b in (edit_button, archive_button, delete_button):
            b.setEnabled(False)
            row_buttons.addWidget(b)
        row_buttons.addStretch()
        layout.addLayout(row_buttons)
        editing = {"id": None}
        archived = {}

        def refresh():
            with self.session_factory() as session:
                accounts = [
                    a for a in AccountService(session).list_accounts()
                    if (a.account_type == AccountType.PENSION.value) == pension
                ]
                archived.clear()
                table.setRowCount(len(accounts))
                for row, item in enumerate(accounts):
                    archived[item.id] = not item.is_active
                    values = [
                        item.id, item.name, item.account_type, item.currency,
                        "Active" if item.is_active else "Archived"
                    ]
                    if pension:
                        balance = AccountService(session).balance(item.id)
                        values.append(f"{from_minor_units(balance):,.2f}")
                    for col, value in enumerate(values):
                        table.setItem(row, col, QTableWidgetItem(str(value)))
            on_selection()
            if pension:
                refresh_activity()

        def clear_form():
            editing["id"] = None
            name.clear()
            opening.setText("0.00")
            currency.setText("EUR")
            button.setText("Add account")
            cancel_button.setVisible(False)

        def selected_id():
            row = table.currentRow()
            item = table.item(row, 0) if row >= 0 else None
            return int(item.text()) if item else None

        def on_selection():
            account_id = selected_id()
            has_selection = account_id is not None
            edit_button.setEnabled(has_selection)
            delete_button.setEnabled(has_selection)
            archive_button.setEnabled(has_selection)
            archive_button.setText(
                "Restore selected" if archived.get(account_id) else "Archive selected"
            )

        def toggle_archive():
            account_id = selected_id()
            if account_id is None:
                return
            restoring = archived.get(account_id, False)
            try:
                with self.session_factory() as session:
                    AccountService(session).set_active(account_id, restoring)
                status.setText("Account restored." if restoring else "Account archived.")
                refresh()
            except Exception as exc:
                QMessageBox.warning(page, "Could not update account", str(exc))

        def begin_edit():
            account_id = selected_id()
            if account_id is None:
                return
            with self.session_factory() as session:
                account = session.get(AccountModel, account_id)
                if account is None:
                    refresh()
                    return
                editing["id"] = account.id
                name.setText(account.name)
                kind.setCurrentText(account.account_type)
                opening.setText(str(from_minor_units(account.opening_balance_minor)))
                currency.setText(account.currency)
            button.setText("Save changes")
            cancel_button.setVisible(True)
            status.setText("Editing account.")

        def delete_selected():
            account_id = selected_id()
            if account_id is None:
                return
            answer = QMessageBox.question(
                page, "Delete account", "Delete the selected account?"
            )
            if answer != QMessageBox.Yes:
                return
            try:
                with self.session_factory() as session:
                    AccountService(session).delete_account(account_id)
                if editing["id"] == account_id:
                    clear_form()
                status.setText("Account deleted.")
                refresh()
            except Exception as exc:
                QMessageBox.warning(page, "Could not delete account", str(exc))

        def add():
            try:
                with self.session_factory() as session:
                    service = AccountService(session)
                    if editing["id"] is None:
                        service.create_account(
                            name.text(), kind.currentText(), opening.text(), currency.text()
                        )
                        message = "Account created."
                    else:
                        service.update_account(
                            editing["id"], name.text(), kind.currentText(),
                            opening.text(), currency.text()
                        )
                        message = "Account updated."
                clear_form()
                status.setText(message)
                refresh()
            except Exception as exc:
                QMessageBox.warning(page, "Could not save account", str(exc))

        button = QPushButton("Add account")
        button.clicked.connect(add)
        cancel_button = QPushButton("Cancel edit")
        cancel_button.setVisible(False)
        cancel_button.clicked.connect(lambda: (clear_form(), status.setText("")))
        edit_button.clicked.connect(begin_edit)
        delete_button.clicked.connect(delete_selected)
        archive_button.clicked.connect(toggle_archive)
        table.itemSelectionChanged.connect(on_selection)
        table.itemDoubleClicked.connect(lambda _: begin_edit())
        layout.addWidget(button)
        layout.addWidget(cancel_button)
        if pension:
            layout.addWidget(self._named(QLabel("Pension activity"), "sectionLabel"))
            activity_form = QFormLayout()
            pension_account = QComboBox()
            pension_account.setObjectName("pensionAccount")
            activity_type = QComboBox()
            activity_type.setObjectName("pensionActivityType")
            activity_type.addItems([
                "Contribution", "Withdrawal", "Valuation gain", "Valuation loss"
            ])
            activity_date = QDateEdit()
            activity_date.setCalendarPopup(True)
            activity_date.setDate(date.today())
            activity_amount = QLineEdit()
            activity_amount.setObjectName("pensionActivityAmount")
            activity_memo = QLineEdit()
            activity_form.addRow("Pension", pension_account)
            activity_form.addRow("Activity", activity_type)
            activity_form.addRow("Date", activity_date)
            activity_form.addRow("Amount", activity_amount)
            activity_form.addRow("Memo", activity_memo)
            layout.addLayout(activity_form)
            totals_label = QLabel()
            layout.addWidget(totals_label)
            activity_table = QTableWidget(0, 4)
            activity_table.setObjectName("pensionActivity")
            activity_table.setHorizontalHeaderLabels(
                ["Date", "Activity", "Memo", "Amount"]
            )
            activity_table.horizontalHeader().setStretchLastSection(True)
            activity_table.setSelectionBehavior(QTableWidget.SelectRows)
            activity_table.setSelectionMode(QTableWidget.SingleSelection)
            activity_table.setEditTriggers(QTableWidget.NoEditTriggers)
            layout.addWidget(activity_table)
            activity_buttons = QHBoxLayout()
            add_activity_button = QPushButton("Add pension activity")
            add_activity_button.setObjectName("addPensionActivity")
            delete_activity_button = QPushButton("Delete selected activity")
            activity_buttons.addWidget(add_activity_button)
            activity_buttons.addWidget(delete_activity_button)
            layout.addLayout(activity_buttons)

            def refresh_activity():
                with self.session_factory() as session:
                    service = AccountService(session)
                    pensions = [
                        a for a in service.list_accounts()
                        if a.account_type == AccountType.PENSION.value
                    ]
                    current = pension_account.currentData()
                    pension_account.blockSignals(True)
                    pension_account.clear()
                    totals = {}
                    for item in pensions:
                        suffix = "" if item.is_active else " - archived"
                        pension_account.addItem(
                            f"{item.name} ({item.currency}){suffix}", item.id
                        )
                        if item.is_active:
                            totals[item.currency] = (
                                totals.get(item.currency, 0) + service.balance(item.id)
                            )
                    index = pension_account.findData(current)
                    if index >= 0:
                        pension_account.setCurrentIndex(index)
                    pension_account.blockSignals(False)
                    totals_label.setText(
                        "Active pension totals: " + (
                            ", ".join(
                                f"{cur} {from_minor_units(value):,.2f}"
                                for cur, value in sorted(totals.items())
                            ) or "None"
                        )
                    )
                    account_id = pension_account.currentData()
                    txs = (
                        TransactionService(session).list_transactions(account_id)
                        if account_id is not None else []
                    )
                    activity_table.setRowCount(len(txs))
                    for row, tx in enumerate(txs):
                        for col, value in enumerate((
                            tx.transaction_date.isoformat(), tx.transaction_type,
                            tx.memo or tx.payee_text,
                            str(from_minor_units(tx.signed_amount_minor)),
                        )):
                            cell = QTableWidgetItem(str(value))
                            cell.setData(Qt.UserRole, tx.id)
                            activity_table.setItem(row, col, cell)

            def add_activity():
                try:
                    with self.session_factory() as session:
                        PensionService(session).add_activity(
                            pension_account.currentData(),
                            activity_date.date().toPython(),
                            activity_amount.text(), activity_type.currentText(),
                            activity_memo.text(),
                        )
                    activity_amount.clear()
                    activity_memo.clear()
                    status.setText("Pension activity saved.")
                    refresh()
                except Exception as exc:
                    QMessageBox.warning(
                        page, "Could not save pension activity", str(exc)
                    )

            def delete_activity():
                row = activity_table.currentRow()
                item = activity_table.item(row, 0) if row >= 0 else None
                if item is None:
                    return
                tx_id = item.data(Qt.UserRole)
                with self.session_factory() as session:
                    tx = session.get(TransactionModel, tx_id)
                    if tx is None:
                        refresh()
                        return
                    text = (
                        "Both sides of this transfer will be deleted."
                        if tx.transfer_id else "Delete the selected pension activity?"
                    )
                answer = QMessageBox.question(page, "Delete activity", text)
                if answer != QMessageBox.Yes:
                    return
                try:
                    with self.session_factory() as session:
                        TransactionService(session).delete_transaction(tx_id)
                    status.setText("Pension activity deleted.")
                    refresh()
                except Exception as exc:
                    QMessageBox.warning(page, "Could not delete activity", str(exc))

            pension_account.activated.connect(refresh_activity)
            add_activity_button.clicked.connect(add_activity)
            delete_activity_button.clicked.connect(delete_activity)
        page.refresh = refresh
        refresh()
        if pension:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            scroll.refresh = refresh
            return scroll
        return page

    def transactions_page(self):
        """Build the transaction entry form, search field, and transaction list."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self._title("Transactions"))
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
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(table)
        row_buttons = QHBoxLayout()
        edit_button = QPushButton("Edit selected")
        delete_button = QPushButton("Delete selected")
        edit_button.setEnabled(False)
        delete_button.setEnabled(False)
        row_buttons.addWidget(edit_button)
        row_buttons.addWidget(delete_button)
        row_buttons.addStretch()
        layout.addLayout(row_buttons)
        editing = {"id": None}
        status = self._named(QLabel(), "statusLabel")
        layout.addWidget(status)

        def refresh():
            with self.session_factory() as session:
                accounts_list = [
                    a for a in AccountService(session).list_accounts()
                    if a.account_type != AccountType.PENSION.value
                ]
                categories_list = CategoryService(session).list_categories()
                current_account = account.currentData()
                account.clear()
                for a in accounts_list:
                    suffix = "" if a.is_active else " - archived"
                    account.addItem(f"{a.name} ({a.currency}){suffix}", a.id)
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
                txs = (
                    TransactionService(session).list_transactions(
                        account_id=account.currentData(), search=search.text()
                    ) if account.currentData() is not None else []
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
                        item = QTableWidgetItem(str(val))
                        item.setData(Qt.UserRole, tx.id)
                        table.setItem(row, col, item)

        def clear_form():
            editing["id"] = None
            amount.clear()
            payee.clear()
            memo.clear()
            button.setText("Add transaction")
            cancel_button.setVisible(False)

        def selected_id():
            row = table.currentRow()
            item = table.item(row, 0) if row >= 0 else None
            return item.data(Qt.UserRole) if item else None

        def on_selection():
            tx_id = selected_id()
            edit_button.setEnabled(tx_id is not None)
            delete_button.setEnabled(tx_id is not None)

        def begin_edit():
            tx_id = selected_id()
            if tx_id is None:
                return
            with self.session_factory() as session:
                tx = session.get(TransactionModel, tx_id)
                if tx is None:
                    refresh()
                    return
                if tx.transfer_id is not None or tx.transaction_type == "Transfer":
                    QMessageBox.information(
                        page, "Transfer",
                        "Transfers cannot be edited. Delete the transfer and create it again."
                    )
                    return
                editing["id"] = tx.id
                account.setCurrentIndex(max(account.findData(tx.account_id), 0))
                tx_type.setCurrentText(tx.transaction_type)
                tx_date.setDate(tx.transaction_date)
                amount.setText(str(abs(from_minor_units(tx.signed_amount_minor))))
                payee.setText(tx.payee_text)
                memo.setText(tx.memo)
                category.setCurrentIndex(max(category.findData(tx.category_id), 0))
            button.setText("Save changes")
            cancel_button.setVisible(True)
            status.setText("Editing transaction.")

        def delete_selected():
            tx_id = selected_id()
            if tx_id is None:
                return
            with self.session_factory() as session:
                tx = session.get(TransactionModel, tx_id)
                is_transfer = tx is not None and tx.transfer_id is not None
            text = "Delete the selected transaction?"
            if is_transfer:
                text = "This is part of a transfer. Both sides of the transfer will be deleted."
            if QMessageBox.question(page, "Delete transaction", text) != QMessageBox.Yes:
                return
            try:
                with self.session_factory() as session:
                    count = TransactionService(session).delete_transaction(tx_id)
                if editing["id"] == tx_id:
                    clear_form()
                status.setText(f"Deleted {count} transaction(s).")
                refresh()
            except Exception as exc:
                QMessageBox.warning(page, "Could not delete transaction", str(exc))

        def add():
            try:
                if account.currentData() is None:
                    raise ValueError("Create an account first")
                with self.session_factory() as session:
                    service = TransactionService(session)
                    if editing["id"] is None:
                        service.add_transaction(
                            account.currentData(), tx_date.date().toPython(),
                            amount.text(), tx_type.currentText(), payee.text(),
                            memo.text(), category.currentData()
                        )
                        message = "Transaction saved."
                    else:
                        service.update_transaction(
                            editing["id"], account.currentData(),
                            tx_date.date().toPython(), amount.text(),
                            tx_type.currentText(), payee.text(), memo.text(),
                            category.currentData()
                        )
                        message = "Transaction updated."
                clear_form()
                status.setText(message)
                refresh()
            except Exception as exc:
                QMessageBox.warning(page, "Could not save transaction", str(exc))

        button = QPushButton("Add transaction")
        button.clicked.connect(add)
        cancel_button = QPushButton("Cancel edit")
        cancel_button.setVisible(False)
        cancel_button.clicked.connect(lambda: (clear_form(), status.setText("")))
        edit_button.clicked.connect(begin_edit)
        delete_button.clicked.connect(delete_selected)
        table.itemSelectionChanged.connect(on_selection)
        table.itemDoubleClicked.connect(lambda _: begin_edit())
        search.textChanged.connect(refresh)
        # activated fires only on user selection, not on refresh() repopulating the list
        account.activated.connect(refresh)
        layout.addWidget(button)
        layout.addWidget(cancel_button)
        page.refresh = refresh
        refresh()
        return page

    def scheduled_transactions_page(self):
        """Build monthly transaction reminders and their manual posting controls."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self._title("Scheduled Transactions"))
        layout.addWidget(QLabel(
            "Monthly reminders are not posted automatically. Review each due item "
            "and post it when appropriate."
        ))

        form = QFormLayout()
        name = QLineEdit()
        account = QComboBox()
        transaction_type = QComboBox()
        transaction_type.addItems(["Expense", "Income"])
        amount = QLineEdit()
        due_date = QDateEdit()
        due_date.setCalendarPopup(True)
        due_date.setDate(date.today())
        category = QComboBox()
        payee = QLineEdit()
        memo = QLineEdit()
        form.addRow("Reminder name", name)
        form.addRow("Account", account)
        form.addRow("Type", transaction_type)
        form.addRow("Amount", amount)
        form.addRow("First due date", due_date)
        form.addRow("Category", category)
        form.addRow("Payee", payee)
        form.addRow("Memo", memo)
        layout.addLayout(form)

        status = self._named(QLabel(), "statusLabel")
        layout.addWidget(status)
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels([
            "Name", "Account", "Type", "Amount", "Next due", "Status"
        ])
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(table)

        action_row = QHBoxLayout()
        add_button = QPushButton("Add monthly reminder")
        post_button = QPushButton("Post due transaction")
        pause_button = QPushButton("Pause selected")
        post_button.setEnabled(False)
        pause_button.setEnabled(False)
        action_row.addWidget(add_button)
        action_row.addWidget(post_button)
        action_row.addWidget(pause_button)
        action_row.addStretch()
        layout.addLayout(action_row)
        schedule_states = {}

        def refresh():
            with self.session_factory() as session:
                accounts_list = [
                    a for a in AccountService(session).list_accounts(active_only=True)
                    if a.account_type != AccountType.PENSION.value
                ]
                categories_list = CategoryService(session).list_categories()
                schedules = ScheduledTransactionService(session).list_schedules()

            selected_account = account.currentData()
            account.blockSignals(True)
            account.clear()
            for item in accounts_list:
                account.addItem(f"{item.name} ({item.currency})", item.id)
            selected_index = account.findData(selected_account)
            if selected_index >= 0:
                account.setCurrentIndex(selected_index)
            account.blockSignals(False)

            selected_category = category.currentData()
            category.clear()
            category.addItem("Uncategorised", None)
            for item in categories_list:
                category.addItem(f"{item.name} ({item.kind})", item.id)
            selected_index = category.findData(selected_category)
            if selected_index >= 0:
                category.setCurrentIndex(selected_index)

            today = date.today()
            account_names = {
                item.id: f"{item.name} ({item.currency})" for item in accounts_list
            }
            schedule_states.clear()
            table.setRowCount(len(schedules))
            for row, item in enumerate(schedules):
                account_name = account_names.get(item.account_id, "Unavailable")
                if not item.is_active:
                    state = "Paused"
                elif item.next_due_date <= today:
                    state = "Due"
                else:
                    state = "Upcoming"
                schedule_states[item.id] = (item.is_active, item.next_due_date)
                values = [
                    item.name,
                    account_name,
                    item.transaction_type,
                    f"{from_minor_units(item.amount_minor):,.2f}",
                    item.next_due_date.isoformat(),
                    state,
                ]
                for column, value in enumerate(values):
                    table_item = QTableWidgetItem(str(value))
                    if column == 0:
                        table_item.setData(Qt.UserRole, item.id)
                    table.setItem(row, column, table_item)
            on_selection()

        def selected_schedule_id():
            row = table.currentRow()
            item = table.item(row, 0) if row >= 0 else None
            return item.data(Qt.UserRole) if item else None

        def on_selection():
            schedule_id = selected_schedule_id()
            state = schedule_states.get(schedule_id)
            selected = state is not None
            pause_button.setEnabled(selected)
            if selected:
                active, next_due = state
                pause_button.setText("Pause selected" if active else "Resume selected")
                post_button.setEnabled(active and next_due <= date.today())
            else:
                post_button.setEnabled(False)

        def add_schedule():
            try:
                if account.currentData() is None:
                    raise ValueError("Create an active account first")
                with self.session_factory() as session:
                    ScheduledTransactionService(session).create_schedule(
                        name.text(),
                        account.currentData(),
                        amount.text(),
                        transaction_type.currentText(),
                        due_date.date().toPython(),
                        category.currentData(),
                        payee.text(),
                        memo.text(),
                    )
                name.clear()
                amount.clear()
                payee.clear()
                memo.clear()
                status.setText("Monthly reminder created.")
                refresh()
            except Exception as exc:
                QMessageBox.warning(page, "Could not create reminder", str(exc))

        def post_selected():
            schedule_id = selected_schedule_id()
            if schedule_id is None:
                return
            try:
                with self.session_factory() as session:
                    ScheduledTransactionService(session).post_due(schedule_id)
                status.setText("Scheduled transaction posted.")
                refresh()
            except Exception as exc:
                QMessageBox.warning(page, "Could not post transaction", str(exc))

        def toggle_pause():
            schedule_id = selected_schedule_id()
            state = schedule_states.get(schedule_id)
            if state is None:
                return
            try:
                with self.session_factory() as session:
                    ScheduledTransactionService(session).set_active(
                        schedule_id, not state[0]
                    )
                status.setText(
                    "Reminder resumed." if not state[0] else "Reminder paused."
                )
                refresh()
            except Exception as exc:
                QMessageBox.warning(page, "Could not update reminder", str(exc))

        table.itemSelectionChanged.connect(on_selection)
        add_button.clicked.connect(add_schedule)
        post_button.clicked.connect(post_selected)
        pause_button.clicked.connect(toggle_pause)
        page.refresh = refresh
        refresh()
        return page

    def transfers_page(self):
        """Build the form for transfers between accounts, with currency conversion."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self._title("Transfers"))
        form = QFormLayout()
        source = QComboBox()
        destination = QComboBox()
        tx_date = QDateEdit()
        tx_date.setCalendarPopup(True)
        tx_date.setDate(date.today())
        amount = QLineEdit()
        rate = QLineEdit()
        rate.setPlaceholderText("Destination units per 1 source unit")
        received = self._named(QLabel(), "receivedLabel")
        memo = QLineEdit()
        form.addRow("From account", source)
        form.addRow("To account", destination)
        form.addRow("Date", tx_date)
        form.addRow("Amount (source currency)", amount)
        rate_label = QLabel("Exchange rate")
        form.addRow(rate_label, rate)
        received_label = QLabel("Amount received")
        form.addRow(received_label, received)
        form.addRow("Memo", memo)
        layout.addLayout(form)
        status = self._named(QLabel(), "statusLabel")
        layout.addWidget(status)
        currencies = {}

        def is_cross_currency():
            src, dst = source.currentData(), destination.currentData()
            return (src is not None and dst is not None
                    and currencies.get(src) != currencies.get(dst))

        def update_preview():
            cross = is_cross_currency()
            for widget in (rate_label, rate, received_label, received):
                widget.setVisible(cross)
            received.setText("")
            if not cross:
                return
            try:
                minor = TransferService.convert_minor(
                    to_minor_units(amount.text()), Decimal(rate.text().strip())
                )
                received.setText(
                    f"{currencies[destination.currentData()]} {from_minor_units(minor):,.2f}"
                )
            except Exception:
                pass

        def refresh():
            with self.session_factory() as session:
                accounts_list = AccountService(session).list_accounts(active_only=True)
            currencies.clear()
            current = (source.currentData(), destination.currentData())
            for box, selected in zip((source, destination), current):
                box.blockSignals(True)
                box.clear()
                for a in accounts_list:
                    box.addItem(f"{a.name} ({a.currency})", a.id)
                    currencies[a.id] = a.currency
                idx = box.findData(selected)
                if idx >= 0:
                    box.setCurrentIndex(idx)
                box.blockSignals(False)
            if destination.currentData() == source.currentData() and destination.count() > 1:
                destination.setCurrentIndex(1 if source.currentIndex() == 0 else 0)
            update_preview()

        def transfer():
            try:
                if source.currentData() is None or destination.currentData() is None:
                    raise ValueError("Create two accounts first")
                with self.session_factory() as session:
                    TransferService(session).create_transfer(
                        source.currentData(), destination.currentData(), amount.text(),
                        tx_date.date().toPython(), memo.text(),
                        rate.text() if is_cross_currency() else None
                    )
                amount.clear()
                status.setText("Transfer saved.")
                update_preview()
            except Exception as exc:
                QMessageBox.warning(page, "Could not save transfer", str(exc))

        button = QPushButton("Transfer funds")
        button.clicked.connect(transfer)
        layout.addWidget(button)
        layout.addStretch()
        source.currentIndexChanged.connect(update_preview)
        destination.currentIndexChanged.connect(update_preview)
        amount.textChanged.connect(update_preview)
        rate.textChanged.connect(update_preview)
        page.refresh = refresh
        refresh()
        return page

    def categories_page(self):
        """Build the category creation form and category listing."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self._title("Categories"))
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
        """Build the income and expense report with account filter, breakdown and export."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self._title("Income and Expenses"))
        account = QComboBox()
        start = QDateEdit()
        start.setCalendarPopup(True)
        start.setDate(date(date.today().year, 1, 1))
        end = QDateEdit()
        end.setCalendarPopup(True)
        end.setDate(date.today())
        form = QFormLayout()
        form.addRow("Account", account)
        form.addRow("From", start)
        form.addRow("To", end)
        layout.addLayout(form)
        layout.addWidget(self._named(QLabel("Totals by currency"), "sectionLabel"))
        summary = QTableWidget(0, 4)
        summary.setHorizontalHeaderLabels(["Currency", "Income", "Expenses", "Net"])
        layout.addWidget(summary)
        layout.addWidget(self._named(QLabel("By category"), "sectionLabel"))
        breakdown = QTableWidget(0, 4)
        breakdown.setHorizontalHeaderLabels(["Category", "Currency", "Income", "Expenses"])
        layout.addWidget(breakdown)
        for table in (summary, breakdown):
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.horizontalHeader().setStretchLastSection(True)
        status = self._named(QLabel(), "statusLabel")
        layout.addWidget(status)

        def money(minor):
            return f"{from_minor_units(minor):,.2f}"

        def fill(table, rows):
            table.setRowCount(len(rows))
            for row, values in enumerate(rows):
                for col, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if col >= len(values) - (3 if table is summary else 2):
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    table.setItem(row, col, item)

        def refresh():
            with self.session_factory() as session:
                accounts_list = [
                    a for a in AccountService(session).list_accounts()
                    if a.account_type != AccountType.PENSION.value
                ]
                current = account.currentData()
                account.blockSignals(True)
                account.clear()
                account.addItem("All accounts", None)
                for a in accounts_list:
                    suffix = "" if a.is_active else " - archived"
                    account.addItem(f"{a.name} ({a.currency}){suffix}", a.id)
                account.setCurrentIndex(max(account.findData(current), 0))
                account.blockSignals(False)
                service = ReportService(session)
                args = (start.date().toPython(), end.date().toPython(), account.currentData())
                totals = service.income_expense(*args)
                categories = service.category_breakdown(*args)
            fill(summary, [
                (cur, money(t["income_minor"]), money(t["expenses_minor"]),
                 money(t["net_minor"]))
                for cur, t in totals.items()
            ])
            fill(breakdown, [
                (c["category"], c["currency"], money(c["income_minor"]),
                 money(c["expenses_minor"]))
                for c in categories
            ])

        def export_csv():
            filename, _ = QFileDialog.getSaveFileName(
                page, "Export transactions", "transactions.csv", "CSV files (*.csv)"
            )
            if not filename:
                return
            try:
                with self.session_factory() as session:
                    txs = ReportService(session).transactions(
                        start.date().toPython(), end.date().toPython(),
                        account.currentData()
                    )
                    export_transactions_csv(txs, filename)
                status.setText(f"Exported {len(txs)} transactions.")
            except Exception as exc:
                QMessageBox.warning(page, "Could not export", str(exc))

        buttons = QHBoxLayout()
        button = QPushButton("Generate report")
        button.clicked.connect(refresh)
        export_button = QPushButton("Export transactions to CSV")
        export_button.clicked.connect(export_csv)
        buttons.addWidget(button)
        buttons.addWidget(export_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        account.activated.connect(refresh)
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
                accounts = AccountService(session).list_accounts(active_only=True)
                choices = [f"{a.id}: {a.name}" for a in accounts]
            if not choices:
                raise ValueError("Create a destination account before importing")
            selected, ok = QInputDialog.getItem(
                self, "Destination account", "Import these records into:", choices, 0, False
            )
            if not ok:
                return
            account_id = int(selected.split(":", 1)[0])
            pension_import = any(
                a.id == account_id and a.account_type == AccountType.PENSION.value
                for a in accounts
            )
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
            self.show_page(
                self.pensions_page if pension_import else self.transactions_page
            )
        except Exception as exc:
            QMessageBox.critical(self, "QIF import failed", str(exc))

    def import_revolut(self):
        """Import a Revolut statement CSV, mapping each Revolut product to an account."""
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select Revolut statement", "", "CSV files (*.csv);;All files (*)"
        )
        if not filename:
            return
        try:
            records = parse_revolut_csv(filename)
            if not records:
                raise ValueError("No transactions were found in the statement")
            with self.session_factory() as session:
                accounts = AccountService(session).list_accounts(active_only=True)
                choices = [f"{a.id}: {a.name} ({a.currency})" for a in accounts]
            if not choices:
                raise ValueError("Create a destination account before importing")
            skip = "Skip this product"
            by_product = {}
            for record in records:
                by_product.setdefault(record["product"], []).append(record)
            plan = {}
            for product, rows in by_product.items():
                selected, ok = QInputDialog.getItem(
                    self, "Destination account",
                    f"Import the {len(rows)} '{product}' rows into:",
                    choices + [skip], 0, False
                )
                if not ok:
                    return
                if selected != skip:
                    plan[product] = int(selected.split(":", 1)[0])
            if not plan:
                return
            lines = [f"{p}: {len(by_product[p])} rows" for p in plan]
            answer = QMessageBox.question(
                self, "Confirm Revolut import",
                f"File: {filename}\n" + "\n".join(lines) +
                "\n\nPending rows are skipped. Commit this import?"
            )
            if answer != QMessageBox.Yes:
                return
            imported = skipped = pending = 0
            with self.session_factory() as session:
                for product, account_id in plan.items():
                    result = ImportService(session).commit_revolut(
                        filename, account_id, by_product[product]
                    )
                    imported += result["imported"]
                    skipped += result["skipped"]
                    pending += result["pending"]
            QMessageBox.information(
                self, "Import complete",
                f"Imported: {imported}\nSkipped duplicates: {skipped}\n"
                f"Skipped pending: {pending}\n"
                "Pension transactions appear in Pensions."
            )
            self.show_page(self.transactions_page)
        except Exception as exc:
            QMessageBox.critical(self, "Revolut import failed", str(exc))
