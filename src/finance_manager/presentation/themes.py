"""Application themes: built-in Light/Dark plus user .qss files from the data folder."""

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from finance_manager.config import data_dir

DEFAULT_THEME = "Light"
_SETTINGS_KEY = "ui/theme"

_TEMPLATE = """
QMainWindow, QWidget {{ background: {bg}; color: {fg}; }}
QLabel {{ background: transparent; }}
QLabel#pageTitle {{ font-size: 24px; font-weight: bold; padding: 4px 0 8px 0; }}
QLabel#sectionLabel {{ font-size: 15px; font-weight: bold; }}
QLabel#noteLabel {{ color: {muted}; }}
QLabel#statusLabel {{ color: {muted}; font-style: italic; }}
QLabel#receivedLabel {{ font-weight: bold; }}
QFrame#card {{
    background: {input_bg}; border: 1px solid {border}; border-radius: 8px;
}}
QLabel#cardValue {{ font-size: 22px; font-weight: bold; }}
QLabel#cardValue[kind="income"] {{ color: {positive}; }}
QLabel#cardValue[kind="expenses"] {{ color: {negative}; }}
QPushButton {{
    background: {accent}; color: {accent_fg}; border: none;
    padding: 6px 12px; border-radius: 4px;
}}
QPushButton:hover {{ background: {accent_hover}; }}
QPushButton:pressed {{ background: {accent_hover}; }}
QLineEdit, QComboBox, QDateEdit, QSpinBox {{
    background: {input_bg}; color: {fg}; border: 1px solid {border};
    padding: 4px; border-radius: 4px;
}}
QComboBox QAbstractItemView {{
    background: {input_bg}; color: {fg};
    selection-background-color: {accent}; selection-color: {accent_fg};
}}
QTableWidget {{
    background: {input_bg}; alternate-background-color: {bg};
    gridline-color: {border}; selection-background-color: {accent};
    selection-color: {accent_fg};
}}
QHeaderView::section {{
    background: {header_bg}; color: {fg}; padding: 4px;
    border: none; border-right: 1px solid {border};
}}
QMessageBox, QInputDialog {{ background: {bg}; }}
"""

_COLORS = {
    "Light": dict(
        bg="#f5f6f8", fg="#1f2328", input_bg="#ffffff", header_bg="#e6e8ec",
        border="#c9ced6", accent="#2563eb", accent_hover="#1d4ed8", accent_fg="#ffffff",
        muted="#59636e", positive="#15803d", negative="#b91c1c",
    ),
    "Dark": dict(
        bg="#1e1f24", fg="#e6e6e6", input_bg="#2a2c33", header_bg="#33363e",
        border="#3a3d46", accent="#3b82f6", accent_hover="#2563eb", accent_fg="#ffffff",
        muted="#9aa0aa", positive="#4ade80", negative="#f87171",
    ),
}
BUILTIN_THEMES = {name: _TEMPLATE.format(**c) for name, c in _COLORS.items()}
_active_theme = DEFAULT_THEME


def chart_colors() -> dict[str, str]:
    """Colours charts should use for the active theme.

    Custom .qss themes have no known palette, so they get the Qt palette's text colour
    on top of the Light chart colours.
    """
    if _active_theme in _COLORS:
        return _COLORS[_active_theme]
    colors = dict(_COLORS[DEFAULT_THEME])
    colors["fg"] = QApplication.instance().palette().windowText().color().name()
    return colors


def custom_themes_dir() -> Path:
    path = data_dir() / "themes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def available_themes() -> dict[str, str]:
    """Return theme name -> stylesheet, with user .qss files added after built-ins."""
    themes = dict(BUILTIN_THEMES)
    for file in sorted(custom_themes_dir().glob("*.qss")):
        try:
            themes[file.stem] = file.read_text(encoding="utf-8")
        except OSError:
            continue
    return themes


def saved_theme() -> str:
    return str(QSettings().value(_SETTINGS_KEY, DEFAULT_THEME))


def apply_theme(name: str) -> str:
    """Apply the named theme to the whole application and remember the choice."""
    global _active_theme
    themes = available_themes()
    if name not in themes:
        name = DEFAULT_THEME
    _active_theme = name
    app = QApplication.instance()
    app.setStyle("Fusion")
    app.setStyleSheet(themes[name])
    QSettings().setValue(_SETTINGS_KEY, name)
    return name
