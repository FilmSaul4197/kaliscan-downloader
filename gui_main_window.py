from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from models import Manga
from gui_widgets import ChapterTableWidget, PrimaryButton, ProgressListWidget, SecondaryButton, SectionCard
from gui_workers import DownloadWorker, ScrapeWorker
from styles import apply_theme, body_font, headline_font


class MainWindow(QMainWindow):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Kaliscan Downloader')
        self.resize(1200, 780)
        self._manga: Optional[Manga] = None
        self._scrape_worker: Optional[ScrapeWorker] = None
        self._download_worker: Optional[DownloadWorker] = None
        self._download_results: Optional[list[dict[str, object]]] = None
        self._output_dir = Path.cwd() / 'downloads'
        self._build_ui()
        self._configure_status_bar()

    def _build_ui(self) -> None:
        central = QWidget(self)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(18)

        # Source card
        self._url_card = SectionCard()
        card_layout = self._url_card.layout()
        assert isinstance(card_layout, QVBoxLayout)

        title = QLabel('Source & Options')
        title.setFont(headline_font(16))
        card_layout.addWidget(title)

        url_row = QHBoxLayout()
        url_row.setSpacing(12)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText('https://kaliscan.io/manga/...')
        self.url_input.setClearButtonEnabled(True)
        url_row.addWidget(self.url_input, stretch=1)
        self.fetch_button = PrimaryButton('Fetch Chapters')
        self.fetch_button.clicked.connect(self._fetch_chapters)
        url_row.addWidget(self.fetch_button)
        card_layout.addLayout(url_row)

        output_row = QHBoxLayout()
        output_row.setSpacing(12)
        self.output_button = SecondaryButton('Choose Output Folder')
        self.output_button.clicked.connect(self._choose_output_dir)
        output_row.addWidget(self.output_button)
        self.output_label = QLabel(str(self._output_dir))
        self.output_label.setFont(body_font(9))
        self.output_label.setWordWrap(True)
        output_row.addWidget(self.output_label, stretch=1)
        card_layout.addLayout(output_row)

        options_layout = QFormLayout()
        options_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.chapter_workers = QSpinBox()
        self.chapter_workers.setRange(1, 6)
        self.chapter_workers.setValue(2)
        self.image_workers = QSpinBox()
        self.image_workers.setRange(1, 12)
        self.image_workers.setValue(6)
        options_layout.addRow('Chapter workers', self.chapter_workers)
        options_layout.addRow('Image workers', self.image_workers)
        card_layout.addLayout(options_layout)

        self.download_button = PrimaryButton('Download Selected')
        self.download_button.clicked.connect(self._start_download)
        self.download_button.setEnabled(False)
        card_layout.addWidget(self.download_button, 0, Qt.AlignmentFlag.AlignRight)

        main_layout.addWidget(self._url_card)

        # Manga overview
        self._info_card = SectionCard()
        info_layout = self._info_card.layout()
        assert isinstance(info_layout, QVBoxLayout)
        self.manga_title = QLabel('No manga loaded yet.')
        self.manga_title.setFont(headline_font(14))
        self.manga_title.setWordWrap(True)
        info_layout.addWidget(self.manga_title)
        self.manga_meta = QLabel('Enter a valid URL to begin.')
        self.manga_meta.setFont(body_font(10))
        self.manga_meta.setWordWrap(True)
        info_layout.addWidget(self.manga_meta)
        main_layout.addWidget(self._info_card)

        # Chapter table
        self.chapter_table = ChapterTableWidget()
        self.chapter_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        main_layout.addWidget(self.chapter_table)

        # Selection controls
        selection_row = QHBoxLayout()
        selection_row.setSpacing(12)
        self.select_all_button = SecondaryButton('Select All')
        self.select_all_button.clicked.connect(self.chapter_table.select_all)
        selection_row.addWidget(self.select_all_button)
        self.clear_selection_button = SecondaryButton('Clear Selection')
        self.clear_selection_button.clicked.connect(self.chapter_table.clear_selection)
        selection_row.addWidget(self.clear_selection_button)
        selection_row.addStretch(1)
        main_layout.addLayout(selection_row)

        # Progress list
        progress_card = SectionCard()
        progress_layout = progress_card.layout()
        assert isinstance(progress_layout, QVBoxLayout)
        progress_title = QLabel('Download Progress')
        progress_title.setFont(headline_font(14))
        progress_layout.addWidget(progress_title)
        self.progress_list = ProgressListWidget()
        progress_layout.addWidget(self.progress_list)
        main_layout.addWidget(progress_card)

        self.setCentralWidget(central)

    def _configure_status_bar(self) -> None:
        status = QStatusBar()
        status.showMessage('Ready')
        self.setStatusBar(status)

    def _choose_output_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, 'Choose download folder', str(self._output_dir))
        if selected:
            self._output_dir = Path(selected)
            self.output_label.setText(str(self._output_dir))

    def _fetch_chapters(self) -> None:
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, 'Missing URL', 'Please enter a Kaliscan manga URL.')
            return
        self._set_fetch_state(is_running=True)
        status_bar = self.statusBar()
        if status_bar:
            status_bar.showMessage('Fetching manga metadata...')
        worker = ScrapeWorker(url)
        worker.finished_success.connect(self._on_scrape_success)
        worker.failed.connect(self._on_scrape_failed)
        worker.finished.connect(lambda: self._set_fetch_state(is_running=False))
        self._scrape_worker = worker
        worker.start()

    def _set_fetch_state(self, *, is_running: bool) -> None:
        self.fetch_button.setEnabled(not is_running)
        self.url_input.setEnabled(not is_running)
        if is_running:
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage('Fetching manga metadata...')
        else:
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage('Ready')

    def _on_scrape_success(self, manga: Manga) -> None:
        self._manga = manga
        self.manga_title.setText(manga.title)
        author = manga.author or 'Unknown author'
        chapter_count = len(manga.chapters)
        meta_lines = [f'Author: {author}', f'Chapters found: {chapter_count}']
        if manga.tags:
            meta_lines.append('Tags: ' + ', '.join(manga.tags[:8]))
        self.manga_meta.setText('\n'.join(meta_lines))
        self.chapter_table.set_chapters(manga.chapters)
        self.progress_list.reset()
        self.download_button.setEnabled(True)
        status_bar = self.statusBar()
        if status_bar:
            status_bar.showMessage('Chapters ready. Select and download when ready.')

    def _on_scrape_failed(self, message: str) -> None:
        QMessageBox.critical(self, 'Scrape failed', message)
        status_bar = self.statusBar()
        if status_bar:
            status_bar.showMessage('Ready')

    def _start_download(self) -> None:
        if not self._manga:
            QMessageBox.warning(self, 'No manga loaded', 'Fetch chapters before downloading.')
            return
        selected = self.chapter_table.selected_chapters()
        if not selected:
            QMessageBox.information(self, 'No chapters selected', 'Select at least one chapter to download.')
            return
        self._set_download_state(is_running=True)
        self.progress_list.reset()
        worker = DownloadWorker(
            self._manga,
            selected,
            self._output_dir,
            chapter_workers=self.chapter_workers.value(),
            image_workers=self.image_workers.value(),
            retries=3,
            backoff=1.5,
        )
        worker.chapter_prepared.connect(self._on_chapter_prepared)
        worker.chapter_started.connect(self._on_chapter_started)
        worker.page_completed.connect(self._on_page_completed)
        worker.chapter_completed.connect(self._on_chapter_completed)
        worker.chapter_failed.connect(self._on_chapter_failed)
        worker.failed.connect(self._on_download_failed)
        worker.finished_success.connect(self._on_download_finished)
        worker.finished.connect(lambda: self._set_download_state(is_running=False))
        self._download_worker = worker
        worker.start()

    def _set_download_state(self, *, is_running: bool) -> None:
        self.download_button.setEnabled(not is_running)
        self.fetch_button.setEnabled(not is_running)
        self.url_input.setEnabled(not is_running)
        self.output_button.setEnabled(not is_running)
        if is_running:
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage('Downloading chapters...')
        else:
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage('Ready')

    def _on_chapter_prepared(self, chapter, pages: int) -> None:
        self.progress_list.set_total_pages(chapter, pages)

    def _on_chapter_started(self, chapter) -> None:
        self.progress_list.ensure_row(chapter)

    def _on_page_completed(self, chapter) -> None:
        self.progress_list.track_page(chapter)

    def _on_chapter_completed(self, chapter, destination) -> None:
        self.progress_list.mark_completed(chapter, Path(destination))

    def _on_chapter_failed(self, chapter, message: str) -> None:
        self.progress_list.mark_failed(chapter, message)

    def _on_download_failed(self, message: str) -> None:
        QMessageBox.critical(self, 'Download failed', message)

    def _on_download_finished(self, results: list[dict[str, object]]) -> None:
        self._download_results = results
        QMessageBox.information(self, 'Download complete', f'Downloaded {len(results)} chapter(s).')

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        if self._scrape_worker and self._scrape_worker.isRunning():
            self._scrape_worker.terminate()
            self._scrape_worker.wait(1000)
        if self._download_worker and self._download_worker.isRunning():
            self._download_worker.terminate()
            self._download_worker.wait(1000)
        if a0:
            a0.accept()


def launch_gui(app) -> MainWindow:
    apply_theme(app)
    window = MainWindow()
    window.show()
    return window
