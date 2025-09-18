from __future__ import annotations

from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication

PRIMARY_COLOR = '#6366F1'
PRIMARY_TEXT = '#F8FAFC'
SECONDARY_TEXT = '#CBD5F5'
BACKGROUND_DARK = '#0F172A'
BACKGROUND_PANEL = '#1E293B'
ACCENT_COLOR = '#22D3EE'
ERROR_COLOR = '#F87171'
SUCCESS_COLOR = '#34D399'
FONT_FAMILY = 'Segoe UI'

_BASE_STYLESHEET = f"""
QWidget {{
    background-color: {BACKGROUND_DARK};
    color: {PRIMARY_TEXT};
    font-family: {FONT_FAMILY};
}}

QFrame#Panel {{
    background-color: {BACKGROUND_PANEL};
    border: 1px solid rgba(148, 163, 184, 0.2);
    border-radius: 14px;
}}

QLineEdit {{
    background-color: rgba(15, 23, 42, 0.6);
    padding: 8px 12px;
    border-radius: 10px;
    border: 1px solid rgba(148, 163, 184, 0.25);
    color: {PRIMARY_TEXT};
}}

QLineEdit:focus {{
    border-color: {ACCENT_COLOR};
}}

QTableWidget {{
    background-color: {BACKGROUND_PANEL};
    alternate-background-color: rgba(148, 163, 184, 0.08);
    gridline-color: rgba(148, 163, 184, 0.2);
    border-radius: 12px;
    padding: 6px;
}}

QHeaderView::section {{
    background-color: rgba(15, 23, 42, 0.9);
    padding: 6px 12px;
    border: none;
    color: {SECONDARY_TEXT};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 4px;
}}

QScrollBar::handle:vertical {{
    background: rgba(148, 163, 184, 0.35);
    min-height: 24px;
    border-radius: 6px;
}}

QProgressBar {{
    background-color: rgba(148, 163, 184, 0.15);
    border-radius: 10px;
    padding: 3px;
    text-visible: false;
}}

QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {PRIMARY_COLOR}, stop:1 {ACCENT_COLOR});
    border-radius: 8px;
}}

QPushButton {{
    border-radius: 10px;
    padding: 9px 18px;
    font-weight: 600;
}}

QPushButton#PrimaryButton {{
    background-color: {PRIMARY_COLOR};
    color: {PRIMARY_TEXT};
}}

QPushButton#PrimaryButton:hover {{
    background-color: #4F46E5;
}}

QPushButton#PrimaryButton:disabled {{
    background-color: rgba(99, 102, 241, 0.35);
    color: rgba(248, 250, 252, 0.5);
}}

QPushButton#SecondaryButton {{
    background-color: rgba(148, 163, 184, 0.18);
    color: {PRIMARY_TEXT};
}}

QPushButton#SecondaryButton:hover {{
    background-color: rgba(148, 163, 184, 0.25);
}}
"""

def apply_theme(app: QApplication) -> None:
    """Apply the global palette and stylesheet for the application."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BACKGROUND_DARK))
    palette.setColor(QPalette.ColorRole.Base, QColor(BACKGROUND_PANEL))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor('#111827'))
    palette.setColor(QPalette.ColorRole.Text, QColor(PRIMARY_TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(BACKGROUND_PANEL))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(PRIMARY_TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(PRIMARY_COLOR))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor('#0F172A'))
    app.setPalette(palette)

    default_font = QFont(FONT_FAMILY, 10)
    app.setFont(default_font)
    app.setStyleSheet(_BASE_STYLESHEET)


def headline_font(size: int = 14, weight: int = QFont.Weight.DemiBold) -> QFont:
    font = QFont(FONT_FAMILY, size)
    font.setWeight(weight)
    return font


def body_font(size: int = 10) -> QFont:
    return QFont(FONT_FAMILY, size)


def success_color() -> QColor:
    return QColor(SUCCESS_COLOR)


def error_color() -> QColor:
    return QColor(ERROR_COLOR)


def accent_color() -> QColor:
    return QColor(ACCENT_COLOR)
