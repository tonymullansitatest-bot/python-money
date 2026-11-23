import logging

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from finance_manager.infrastructure.openai_assistant import (
    MAX_PROMPT_LENGTH,
    AssistantError,
    OpenAIAssistant,
)

logger = logging.getLogger(__name__)


class _WorkerSignals(QObject):
    finished = Signal(str, bool)


class _AssistantWorker(QRunnable):
    def __init__(self, prompt: str):
        super().__init__()
        self.prompt = prompt
        self.signals = _WorkerSignals()

    def run(self):
        try:
            result = OpenAIAssistant().ask(self.prompt)
        except AssistantError as exc:
            self.signals.finished.emit(str(exc), False)
        except Exception:
            logger.error("Unexpected error while requesting an AI response")
            self.signals.finished.emit(
                "An unexpected error occurred. Please try again.", False
            )
        else:
            self.signals.finished.emit(result, True)


class AIPage(QWidget):
    def __init__(self):
        super().__init__()
        self._worker = None
        layout = QVBoxLayout(self)
        title = QLabel("AI Assistant")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        note = QLabel(
            "Ask a general finance question or summarise non-sensitive text. "
            "Do not enter account details, transactions, names, credentials or other "
            "personal information. Nothing from your database is sent automatically."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(QLabel("Your text"))
        self.prompt = QPlainTextEdit()
        self.prompt.setObjectName("aiPrompt")
        self.prompt.setPlaceholderText(
            "For example: Explain how compound interest works."
        )
        layout.addWidget(self.prompt)
        self.button = QPushButton("Send to OpenAI")
        self.button.setObjectName("aiSend")
        self.button.clicked.connect(self._send)
        layout.addWidget(self.button)
        self.status = QLabel()
        self.status.setObjectName("statusLabel")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(QLabel("Response (not financial advice)"))
        self.response = QPlainTextEdit()
        self.response.setObjectName("aiResponse")
        self.response.setReadOnly(True)
        layout.addWidget(self.response)

    def _send(self):
        prompt = self.prompt.toPlainText().strip()
        if not prompt:
            self.status.setText("Enter a question or text to summarise.")
            return
        if len(prompt) > MAX_PROMPT_LENGTH:
            self.status.setText(f"Text must be at most {MAX_PROMPT_LENGTH} characters.")
            return
        confirmed = QMessageBox.question(
            self,
            "Send to OpenAI",
            "The text above will be sent to OpenAI and may incur charges. "
            "OpenAI's data retention policy applies. "
            "Confirm that it contains no sensitive or personal information.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmed != QMessageBox.Yes:
            return
        self.button.setEnabled(False)
        self.response.clear()
        self.status.setText("Waiting for OpenAI...")
        self._worker = _AssistantWorker(prompt)
        self._worker.signals.finished.connect(self._finished)
        QThreadPool.globalInstance().start(self._worker)

    def _finished(self, message: str, success: bool):
        self.button.setEnabled(True)
        if success:
            self.response.setPlainText(message)
            self.status.setText("Response received.")
        else:
            self.status.setText(message)
        self._worker = None
