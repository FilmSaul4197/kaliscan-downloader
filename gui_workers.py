from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from downloader import ChapterDownloader, DownloadError
from models import Chapter, Manga
from scraper import ScraperError, scrape_manga, scrape_pages
from converter import (
    convert_to_cbz,
    convert_to_pdf,
    get_image_files,
    cleanup_images,
    ConversionError,
)


class ScrapeWorker(QThread):
    finished_success = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, url: str, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._url = url

    def run(self) -> None:  # noqa: D401
        try:
            manga = asyncio.run(scrape_manga(self._url))
        except ScraperError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(f'Unexpected error: {exc}')
        else:
            self.finished_success.emit(manga)


class DownloadWorker(QThread):
    chapter_prepared = pyqtSignal(object, int)
    chapter_started = pyqtSignal(object)
    page_completed = pyqtSignal(object)
    chapter_completed = pyqtSignal(object, object)
    chapter_failed = pyqtSignal(object, str)
    failed = pyqtSignal(str)
    finished_success = pyqtSignal(object)

    def __init__(
        self,
        manga: Manga,
        chapters: Iterable[Chapter],
        output_dir: Path,
        *,
        chapter_workers: int = 2,
        image_workers: int = 6,
        retries: int = 3,
        backoff: float = 1.5,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._manga = manga
        self._chapters = list(chapters)
        self._output_dir = Path(output_dir)
        self._chapter_workers = chapter_workers
        self._image_workers = image_workers
        self._retries = retries
        self._backoff = backoff
        self._downloaded: List[dict[str, object]] = []

    def run(self) -> None:  # noqa: D401
        try:
            result = asyncio.run(self._run_download())
        except DownloadError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(f'Unexpected error: {exc}')
        else:
            self.finished_success.emit(result)

    async def _run_download(self) -> List[dict[str, object]]:
        if not self._chapters:
            return []

        async with ChapterDownloader(
            output_dir=self._output_dir,
            max_chapter_workers=self._chapter_workers,
            max_image_workers=self._image_workers,
            retries=self._retries,
            backoff=self._backoff,
            progress_callback=self._handle_progress,
        ) as downloader:
            async with downloader.get_browser_context() as context:
                scrape_tasks = [scrape_pages(chapter, context) for chapter in self._chapters]
                results = await asyncio.gather(*scrape_tasks, return_exceptions=True)

            chapters_to_download: List[Chapter] = []
            for chapter, result in zip(self._chapters, results):
                if isinstance(result, Exception):
                    self.chapter_failed.emit(chapter, f'Failed to scrape pages: {result}')
                    chapter.pages = []
                else:
                    if isinstance(result, list):
                        chapter.pages = result
                    else:
                        chapter.pages = []
                    self.chapter_prepared.emit(chapter, len(chapter.pages))
                if chapter.pages:
                    chapters_to_download.append(chapter)

            if chapters_to_download:
                await downloader.download(self._manga, chapters_to_download)

        return self._downloaded

    def _handle_progress(self, event: str, payload: dict[str, object]) -> None:
        chapter = payload.get('chapter')
        if not isinstance(chapter, Chapter):
            return
        if event == 'chapter_started':
            self.chapter_started.emit(chapter)
        elif event == 'page_completed':
            self.page_completed.emit(chapter)
        elif event == 'chapter_completed':
            destination = payload.get('destination')
            if isinstance(destination, Path):
                path_obj = destination
            else:
                path_obj = Path(str(destination))
            self._downloaded.append({'chapter': chapter, 'path': path_obj})
            self.chapter_completed.emit(chapter, path_obj)
        elif event == 'chapter_failed':
            error = payload.get('error')
            message = str(error) if error is not None else 'Chapter download failed'
            self.chapter_failed.emit(chapter, message)


class ConvertWorker(QThread):
    finished = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(
        self,
        manga: Manga,
        downloaded_chapters: List[dict[str, object]],
        output_dir: Path,
        format: str,
        cleanup: bool,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._manga = manga
        self._downloaded_chapters = downloaded_chapters
        self._output_dir = output_dir
        self._format = format
        self._cleanup = cleanup

    def run(self) -> None:
        try:
            for item in self._downloaded_chapters:
                chapter: Chapter = item["chapter"]  # type: ignore
                chapter_path: Path = item["path"]  # type: ignore
                
                image_files = get_image_files(chapter_path)
                if not image_files:
                    continue

                output_filename = f"{chapter_path.name}.{self._format}"
                output_file = self._output_dir / self._manga.id / output_filename
                
                if self._format == "pdf":
                    convert_to_pdf(image_files, output_file)
                elif self._format == "cbz":
                    convert_to_cbz(image_files, output_file)

                if self._cleanup:
                    cleanup_images(image_files)
                    try:
                        chapter_path.rmdir()
                    except OSError:
                        pass
        except (ConversionError, OSError) as exc:
            self.failed.emit(str(exc))
        else:
            self.finished.emit()
