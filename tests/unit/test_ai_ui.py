from unittest.mock import MagicMock

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QMessageBox

from finance_manager.infrastructure.database import build_session_factory
from finance_manager.infrastructure.openai_assistant import AssistantError
from finance_manager.presentation.ai_page import AIPage
from finance_manager.presentation.main_window import FinanceMainWindow


def test_ai_page_is_accessible_from_main_window(session, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = FinanceMainWindow(build_session_factory(session.get_bind()))
    window.show_page(window.ai_page)
    assert isinstance(window.stack.currentWidget(), AIPage)
    window.close()
    app.processEvents()


def test_confirmation_and_background_response(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    ask = MagicMock(return_value="Compound interest adds interest on prior interest.")
    monkeypatch.setattr("finance_manager.presentation.ai_page.OpenAIAssistant.ask", ask)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.No)
    page = AIPage()
    page.prompt.setPlainText("Explain compound interest")
    page.button.click()
    ask.assert_not_called()
    assert page.button.isEnabled()

    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    page.button.click()
    assert not page.button.isEnabled()
    assert QThreadPool.globalInstance().waitForDone(5000)
    app.processEvents()
    ask.assert_called_once_with("Explain compound interest")
    assert page.response.toPlainText() == (
        "Compound interest adds interest on prior interest."
    )
    assert page.button.isEnabled()
    page.close()


def test_background_error_is_displayed(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    def fail(_self, _prompt):
        raise AssistantError("OpenAI request failed.")

    monkeypatch.setattr(
        "finance_manager.presentation.ai_page.OpenAIAssistant.ask", fail
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    page = AIPage()
    page.prompt.setPlainText("Explain interest")
    page.button.click()
    assert QThreadPool.globalInstance().waitForDone(5000)
    app.processEvents()
    assert page.status.text() == "OpenAI request failed."
    assert page.button.isEnabled()
    page.close()
