from __future__ import annotations

import asyncio
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, async_playwright

from models import Chapter, Manga, Page
from utils import (
    ManifestStore,
    build_chapter_directory,
    format_chapter_label,
    get_logger,
    sanitize_filename,
)

ProgressPayload = Dict[str, object]
ProgressCallback = Callable[[str, ProgressPayload], None]


class DownloadError(RuntimeError):
    """Raised when a download fails permanently."""


_logger = get_logger(__name__)


class ImageDownloader:
    def __init__(
        self,
        *,
        manifest: ManifestStore,
        max_workers: int = 6,
        retries: int = 3,
        backoff: float = 1.5,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> None:
        self.manifest = manifest
        self.max_workers = max_workers
        self.retries = retries
        self.backoff = backoff
        self.progress_callback = progress_callback
        self.semaphore = asyncio.Semaphore(max_workers)

    async def download(
        self, chapter: Chapter, pages: List[Page], destination: Path, context: BrowserContext
    ) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        self.manifest.ensure_chapter(chapter.id)
        self.manifest.update_chapter(
            chapter.id,
            title=chapter.title,
            number=chapter.number,
            url=chapter.url,
            output=str(destination),
            total_pages=len(pages),
        )
        already_downloaded = set(self.manifest.chapter_entry(chapter.id).get("downloaded_pages", []))

        if not pages:
            return

        tasks = [
            self._download_page_with_retry(page, destination, context)
            for page in pages
            if page.index not in already_downloaded
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for page, result in zip(pages, results):
            if isinstance(result, Exception):
                self._notify_page_failed(chapter, page, result)
                raise DownloadError(f"Page download failed for {page.url}") from result
            self._notify_page_completed(chapter, page, result)

    async def _download_page_with_retry(
        self, page: Page, destination: Path, context: BrowserContext
    ) -> Path:
        async with self.semaphore:
            last_error = None
            for attempt in range(self.retries):
                try:
                    pw_page = await context.new_page()
                    response = await pw_page.request.get(page.url)
                    await pw_page.close()

                    if not response.ok:
                        raise DownloadError(f"HTTP {response.status} for {page.url}")

                    raw_name = page.filename or f"{page.index:03d}"
                    safe_name = sanitize_filename(raw_name)
                    parts = safe_name.rsplit(".", 1)
                    base_name = parts[0]
                    provided_ext = f".{parts[1]}" if len(parts) == 2 else ""
                    content_type = response.headers.get("Content-Type")
                    extension = _infer_extension(page.url, content_type) or provided_ext or ".jpg"
                    target = destination / f"{base_name}{extension}"

                    with target.open("wb") as handle:
                        handle.write(await response.body())
                    return target
                except Exception as exc:
                    last_error = exc
                    wait = self.backoff * (2**attempt)
                    _logger.warning(
                        "Retrying page %s (%s) in %.1fs due to %s",
                        page.index,
                        page.url,
                        wait,
                        exc,
                    )
                    await asyncio.sleep(wait)
            raise DownloadError(f"Failed to download {page.url}") from last_error

    def _notify_page_completed(self, chapter: Chapter, page: Page, file_path: Path) -> None:
        self.manifest.mark_page_downloaded(chapter.id, page.index)
        self._notify("page_completed", {"chapter": chapter, "page": page, "file": file_path})

    def _notify_page_failed(self, chapter: Chapter, page: Page, error: Exception) -> None:
        self.manifest.update_chapter(chapter.id, status="error")
        self._notify("page_failed", {"chapter": chapter, "page": page, "error": error})

    def _notify(self, event: str, payload: ProgressPayload) -> None:
        if self.progress_callback:
            self.progress_callback(event, payload)


class ChapterDownloader:
    def __init__(
        self,
        *,
        output_dir: Path | str = "downloads",
        manifest_path: Optional[Path | str] = None,
        max_chapter_workers: int = 2,
        max_image_workers: int = 6,
        retries: int = 3,
        backoff: float = 1.5,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.manifest = ManifestStore(manifest_path or self.output_dir / "manifest.json")
        self.progress_callback = progress_callback
        self.max_chapter_workers = max_chapter_workers
        self.image_downloader = ImageDownloader(
            manifest=self.manifest,
            max_workers=max_image_workers,
            retries=retries,
            backoff=backoff,
            progress_callback=progress_callback,
        )
        self._playwright: Optional[Any] = None
        self._browser: Optional[Browser] = None

    async def __aenter__(self) -> "ChapterDownloader":
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def download(
        self,
        manga: Manga,
        chapters: Iterable[Chapter],
        page_loader: Callable[[Chapter, BrowserContext], Coroutine[Any, Any, List[Page]]],
    ) -> None:
        chapter_list = list(chapters)
        if not chapter_list:
            return

        context = await self._browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        try:
            semaphore = asyncio.Semaphore(self.max_chapter_workers)
            tasks = [
                self._download_chapter_with_semaphore(manga, chapter, page_loader, context, semaphore)
                for chapter in chapter_list
            ]
            await asyncio.gather(*tasks)
        finally:
            await context.close()

    async def _download_chapter_with_semaphore(
        self,
        manga: Manga,
        chapter: Chapter,
        page_loader: Callable[[Chapter, BrowserContext], Coroutine[Any, Any, List[Page]]],
        context: BrowserContext,
        semaphore: asyncio.Semaphore,
    ) -> None:
        async with semaphore:
            await self._download_chapter(manga, chapter, page_loader, context)

    async def _download_chapter(
        self,
        manga: Manga,
        chapter: Chapter,
        page_loader: Callable[[Chapter, BrowserContext], Coroutine[Any, Any, List[Page]]],
        context: BrowserContext,
    ) -> None:
        label = format_chapter_label(chapter.title, chapter.number)
        destination = build_chapter_directory(self.output_dir, manga.title, label)
        self._notify_chapter_started(chapter, destination)

        try:
            pages = await page_loader(chapter, context)
            chapter.pages = pages
            await self.image_downloader.download(chapter, pages, destination, context)
            self._notify_chapter_completed(chapter, destination)
        except Exception as exc:
            _logger.exception("Chapter download failed for %s", chapter.title)
            self._notify_chapter_failed(chapter, exc)
            # Re-raise to be caught by the gather call
            raise

    def _notify_chapter_started(self, chapter: Chapter, destination: Path) -> None:
        self.manifest.ensure_chapter(
            chapter.id,
            {
                "title": chapter.title,
                "number": chapter.number,
                "url": chapter.url,
                "output": str(destination),
                "status": "in_progress",
            },
        )
        self._notify("chapter_started", {"chapter": chapter, "destination": destination})

    def _notify_chapter_completed(self, chapter: Chapter, destination: Path) -> None:
        self.manifest.update_chapter(chapter.id, status="completed")
        self._notify("chapter_completed", {"chapter": chapter, "destination": destination})

    def _notify_chapter_failed(self, chapter: Chapter, error: Exception) -> None:
        self.manifest.update_chapter(chapter.id, status="error")
        self._notify("chapter_failed", {"chapter": chapter, "error": error})

    def _notify(self, event: str, payload: ProgressPayload) -> None:
        if self.progress_callback:
            self.progress_callback(event, payload)


def _infer_extension(url: str, content_type: Optional[str]) -> Optional[str]:
    parsed = urlparse(url) if url else None
    if parsed and parsed.path:
        path_ext = Path(parsed.path).suffix
        if path_ext and len(path_ext) <= 5:
            return path_ext
    if content_type:
        mime = content_type.split(";")[0].strip()
        ext = mimetypes.guess_extension(mime)
        if ext == ".jpe":
            ext = ".jpg"
        return ext
    return None
