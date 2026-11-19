import sys

from PySide6.QtWidgets import QApplication

from finance_manager.infrastructure.database import (
    build_engine, build_session_factory, initialize_database
)
from finance_manager.presentation.main_window import FinanceMainWindow


def main():
    engine = build_engine()
    initialize_database(engine)
    session_factory = build_session_factory(engine)

    app = QApplication(sys.argv)
    app.setApplicationName("Personal Finance Manager")
    window = FinanceMainWindow(session_factory)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
