from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models import Chapter
from styles import SECONDARY_TEXT, body_font, headline_font, success_color, error_color


class PrimaryButton(QPushButton):
    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName('PrimaryButton')
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class SecondaryButton(QPushButton):
    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName('SecondaryButton')
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class SectionCard(QFrame):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName('Panel')
        self.setFrameShape(QFrame.Shape.NoFrame)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)


class ChapterTableWidget(QTableWidget):
    headers = ['Select', 'Chapter', 'Title', 'Published']

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(0, len(self.headers), parent)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        h_header = self.horizontalHeader()
        if h_header:
            h_header.setStretchLastSection(True)
            h_header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        v_header = self.verticalHeader()
        if v_header:
            v_header.setVisible(False)
        for index, title in enumerate(self.headers):
            item = QTableWidgetItem(title)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.setHorizontalHeaderItem(index, item)
        self.setColumnWidth(0, 72)
        self._chapters: List[Chapter] = []

    def set_chapters(self, chapters: Iterable[Chapter]) -> None:
        data = list(chapters)
        self._chapters = data
        self.setRowCount(len(data))
        for row, chapter in enumerate(data):
            select_item = QTableWidgetItem()
            select_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            select_item.setCheckState(Qt.CheckState.Checked if row == 0 else Qt.CheckState.Unchecked)
            self.setItem(row, 0, select_item)

            chapter_item = QTableWidgetItem(self._format_chapter_label(chapter))
            title_item = QTableWidgetItem(chapter.title)
            published_item = QTableWidgetItem(self._format_published(chapter))

            for item in (chapter_item, title_item, published_item):
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

            self.setItem(row, 1, chapter_item)
            self.setItem(row, 2, title_item)
            self.setItem(row, 3, published_item)

        self.resizeColumnsToContents()

    def selected_chapters(self) -> List[Chapter]:
        selected: List[Chapter] = []
        for row, chapter in enumerate(self._chapters):
            item = self.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                selected.append(chapter)
        return selected

    def select_all(self) -> None:
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked)

    def clear_selection(self) -> None:
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)

    def toggle_row(self, row: int) -> None:
        item = self.item(row, 0)
        if item:
            new_state = Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked
            item.setCheckState(new_state)

    @staticmethod
    def _format_chapter_label(chapter: Chapter) -> str:
        if chapter.number is None:
            return chapter.title or 'Chapter'
        return f"{chapter.number:g}"

    @staticmethod
    def _format_published(chapter: Chapter) -> str:
        if chapter.published_at:
            return chapter.published_at.strftime('%Y-%m-%d')
        return 'Unknown'


@dataclass
class _ProgressRow:
    container: QFrame
    title_label: QLabel
    status_label: QLabel
    progress_bar: QProgressBar
    total_pages: int = 0
    completed_pages: int = 0

    def set_total_pages(self, total: int) -> None:
        self.total_pages = max(total, 0)
        if total > 0:
            self.progress_bar.setMaximum(total)
        else:
            self.progress_bar.setMaximum(0)
        self.progress_bar.setValue(0)
        self.completed_pages = 0
        self.status_label.setText('Waiting to start')

    def increment(self, value: int = 1) -> None:
        self.completed_pages += value
        if self.total_pages:
            self.progress_bar.setValue(min(self.completed_pages, self.total_pages))
            self.status_label.setText(f'Downloaded {self.completed_pages}/{self.total_pages} pages')
        else:
            self.progress_bar.setMaximum(0)
            self.status_label.setText(f'Downloaded {self.completed_pages} pages')

    def mark_completed(self, destination: Path) -> None:
        maximum = self.progress_bar.maximum()
        if maximum:
            self.progress_bar.setValue(maximum)
        self.progress_bar.setStyleSheet('')
        self.status_label.setText(f'Complete - {destination}')
        self.title_label.setStyleSheet(f'color: {success_color().name()}')

    def mark_failed(self, message: str) -> None:
        self.status_label.setText(message)
        self.title_label.setStyleSheet(f'color: {error_color().name()}')
        self.progress_bar.setStyleSheet(f'QProgressBar::chunk {{ background: {error_color().name()}; }}')


class ProgressListWidget(QScrollArea):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(10)
        self._layout.addStretch(1)
        self.setWidget(self._container)
        self._rows: Dict[str, _ProgressRow] = {}

    def reset(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if not item:
                continue
            
            widget = item.widget()
            if not widget:
                continue

            widget.deleteLater()
            if widget:
                widget.deleteLater()
        self._rows.clear()
        self._layout.addStretch(1)

    def ensure_row(self, chapter: Chapter) -> _ProgressRow:
        existing = self._rows.get(chapter.id)
        if existing:
            return existing

        container = QFrame()
        container.setObjectName('Panel')
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        title = QLabel(self._format_title(chapter))
        title.setFont(headline_font(12))

        status = QLabel('Waiting to start')
        status.setFont(body_font(10))
        status.setStyleSheet(f'color: {SECONDARY_TEXT}')

        progress = QProgressBar()
        progress.setMinimum(0)
        progress.setMaximum(0)
        progress.setValue(0)

        layout.addWidget(title)
        layout.addWidget(progress)
        layout.addWidget(status)

        # Remove trailing stretch before inserting the new row
        if self._layout.count():
            last_index = self._layout.count() - 1
            last_item = self._layout.itemAt(last_index)
            if last_item and last_item.spacerItem():
                self._layout.takeAt(last_index)

        self._layout.addWidget(container)
        self._layout.addStretch(1)

        row = _ProgressRow(container, title, status, progress)
        self._rows[chapter.id] = row
        return row

    def set_total_pages(self, chapter: Chapter, total: int) -> None:
        row = self.ensure_row(chapter)
        row.set_total_pages(total)

    def track_page(self, chapter: Chapter) -> None:
        row = self.ensure_row(chapter)
        row.increment()

    def mark_completed(self, chapter: Chapter, destination: Path) -> None:
        row = self.ensure_row(chapter)
        row.mark_completed(destination)

    def mark_failed(self, chapter: Chapter, message: str) -> None:
        row = self.ensure_row(chapter)
        row.mark_failed(message)

    @staticmethod
    def _format_title(chapter: Chapter) -> str:
        if chapter.number is not None and chapter.title:
            return f'Chapter {chapter.number:g} - {chapter.title}'
        if chapter.number is not None:
            return f'Chapter {chapter.number:g}'
        return chapter.title or 'Chapter'
