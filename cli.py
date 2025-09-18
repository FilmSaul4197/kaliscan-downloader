from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Coroutine, Dict, Iterable, List, Optional, TYPE_CHECKING

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from downloader import ChapterDownloader, DownloadError
from models import Chapter, Manga, Page
from scraper import ScraperError, scrape_manga, scrape_pages
from utils import get_logger
from converter import (
    convert_to_cbz,
    convert_to_pdf,
    get_image_files,
    cleanup_images,
    ConversionError,
)

if TYPE_CHECKING:  # pragma: no cover
    from playwright.async_api import BrowserContext

app = typer.Typer(help="Kaliscan manga downloader CLI")
console = Console()
_logger = get_logger(__name__)


@app.command()
def scrape(url: str) -> None:
    """Scrape manga metadata and list chapters."""
    asyncio.run(scrape_async(url))


async def scrape_async(url: str) -> None:
    try:
        manga = await scrape_manga(url)
    except ScraperError as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    _display_manga(manga)
    _render_chapter_table(manga)


@app.command()
def download(
    url: str = typer.Option(..., "--url", "-u", help="Manga URL"),
    chapter: Optional[str] = typer.Option(None, "--chapter", "-c", help="Download a single chapter number"),
    chapter_range: Optional[str] = typer.Option(None, "--range", "-r", help="Download a range like 5-10"),
    all_chapters: bool = typer.Option(False, "--all", help="Download all chapters"),
    output: Path = typer.Option(Path("downloads"), "--output", "-o", help="Target download directory"),
    chapter_workers: int = typer.Option(2, "--chapter-workers", help="Concurrent chapter downloads"),
    image_workers: int = typer.Option(6, "--image-workers", help="Concurrent page downloads"),
    retries: int = typer.Option(3, "--retries", help="Retry attempts per request"),
    backoff: float = typer.Option(1.5, "--backoff", help="Backoff multiplier between retries"),
) -> None:
    """Download one or more manga chapters."""
    asyncio.run(
        download_async(
            url,
            chapter,
            chapter_range,
            all_chapters,
            output,
            chapter_workers,
            image_workers,
            retries,
            backoff,
        )
    )


async def download_async(
    url: str,
    chapter_str: Optional[str],
    chapter_range: Optional[str],
    all_chapters: bool,
    output: Path,
    chapter_workers: int,
    image_workers: int,
    retries: int,
    backoff: float,
) -> None:
    try:
        manga = await scrape_manga(url)
    except ScraperError as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    selected = _select_chapters(manga.chapters, chapter_str, chapter_range, all_chapters)
    if not selected:
        typer.secho("No chapters matched your selection.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)

    console.print(f"[bold green]Downloading {len(selected)} chapter(s) from {manga.title}[/bold green]")

    try:
        await _run_download(
            manga,
            selected,
            output,
            chapter_workers,
            image_workers,
            retries,
            backoff,
        )
    except DownloadError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.secho("Download complete.", fg=typer.colors.GREEN)


@app.command()
def interactive(
    output: Path = typer.Option(Path("downloads"), "--output", "-o", help="Default download directory"),
    chapter_workers: int = typer.Option(2, "--chapter-workers", help="Default concurrent chapter downloads"),
    image_workers: int = typer.Option(6, "--image-workers", help="Default concurrent page downloads"),
    retries: int = typer.Option(3, "--retries", help="Default retry attempts per request"),
    backoff: float = typer.Option(1.5, "--backoff", help="Default retry backoff multiplier"),
) -> None:
    """Launch an interactive prompt that guides the download flow."""
    asyncio.run(interactive_async(output, chapter_workers, image_workers, retries, backoff))


async def interactive_async(
    output: Path,
    chapter_workers: int,
    image_workers: int,
    retries: int,
    backoff: float,
) -> None:
    typer.echo("Press Ctrl+C or type 'quit' at any prompt to exit.")

    while True:
        url = typer.prompt("Enter manga URL", prompt_suffix=": ").strip()
        if not url:
            typer.secho("A URL is required.", fg=typer.colors.YELLOW)
            continue
        if url.lower() in {"quit", "q", "exit"}:
            typer.secho("Aborted.", fg=typer.colors.YELLOW)
            raise typer.Exit(code=0)
        try:
            manga = await scrape_manga(url)
        except ScraperError as exc:
            typer.secho(f"Error: {exc}", fg=typer.colors.RED)
            if not typer.confirm("Try another URL?", default=True):
                raise typer.Exit(code=1) from exc
            continue
        break

    _display_manga(manga)
    _render_chapter_table(manga)

    selected = _prompt_chapter_selection(list(manga.chapters))
    if selected is None:
        typer.secho("Aborted.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)

    console.print(f"[bold]{len(selected)}[/bold] chapter(s) selected: " + ", ".join(_chapter_display_name(ch) for ch in selected[:8]))
    if len(selected) > 8:
        console.print("...and more")

    output_input = typer.prompt("Output directory", default=str(output))
    output_path = Path(output_input).expanduser()

    chapter_workers = typer.prompt("Chapter worker limit", default=chapter_workers, type=int)
    image_workers = typer.prompt("Image worker limit", default=image_workers, type=int)
    retries = typer.prompt("Retry attempts", default=retries, type=int)
    backoff = typer.prompt("Retry backoff multiplier", default=backoff, type=float)

    conversion_format = typer.prompt(
        "Convert to PDF/CBZ (optional, leave blank for none)", default="", show_choices=False
    ).lower()
    delete_after_conversion = False
    if conversion_format in {"pdf", "cbz"}:
        delete_after_conversion = typer.confirm("Delete original images after conversion?", default=False)

    if not typer.confirm("Start download now?", default=True):
        typer.secho("Aborted.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)

    console.print(f"[bold green]Downloading {len(selected)} chapter(s) from {manga.title}[/bold green]")

    downloaded_chapters_info = []
    try:
        downloaded_chapters_info = await _run_download(
            manga,
            selected,
            output_path,
            chapter_workers,
            image_workers,
            retries,
            backoff,
        )
    except DownloadError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.secho("Download complete.", fg=typer.colors.GREEN)

    if conversion_format and downloaded_chapters_info:
        _perform_conversion(
            manga, downloaded_chapters_info, output_path, conversion_format, delete_after_conversion
        )


def _display_manga(manga: Manga) -> None:
    console.print(f"[bold]{manga.title}[/bold] ({manga.total_chapters or len(manga.chapters)} chapters)")
    if manga.author:
        console.print(f"Author: {manga.author}")
    if manga.last_updated:
        console.print(f"Last Updated: {manga.last_updated}")
    if manga.tags:
        console.print("Tags: " + ", ".join(manga.tags))
    if manga.description:
        console.print("\n" + manga.description.strip())


def _render_chapter_table(manga: Manga) -> None:
    table = Table(title="Chapters", show_edge=False)
    table.add_column("#", justify="right")
    table.add_column("Title")
    table.add_column("URL", overflow="fold")

    for index, chapter in enumerate(manga.chapters, start=1):
        label = f"{chapter.number:g}" if chapter.number is not None else str(index)
        table.add_row(label, chapter.title, chapter.url)

    console.print(table)


def _select_chapters(
    chapters: Iterable[Chapter],
    chapter: Optional[str],
    chapter_range: Optional[str],
    all_chapters: bool,
) -> List[Chapter]:
    chapter_list = list(chapters)
    if all_chapters or (chapter is None and chapter_range is None):
        return chapter_list

    if chapter and chapter_range:
        raise typer.BadParameter("Use either --chapter or --range, not both.")

    if chapter:
        try:
            target = float(chapter)
        except ValueError as exc:
            raise typer.BadParameter("Chapter must be a number.") from exc
        matches = [c for c in chapter_list if c.number == target]
        if matches:
            return matches
        index = int(target)
        if 1 <= index <= len(chapter_list):
            return [chapter_list[index - 1]]
        return []

    if chapter_range:
        parts = chapter_range.split("-", 1)
        if len(parts) != 2:
            raise typer.BadParameter("Range must look like start-end.")
        try:
            start = float(parts[0])
            end = float(parts[1])
        except ValueError as exc:
            raise typer.BadParameter("Range boundaries must be numbers.") from exc
        start, end = sorted((start, end))
        selected = [c for c in chapter_list if c.number and start <= c.number <= end]
        if selected:
            return selected
        start_index = max(int(start), 1)
        end_index = min(int(end), len(chapter_list))
        return chapter_list[start_index - 1 : end_index]

    return []


def _prompt_chapter_selection(chapters: List[Chapter]) -> Optional[List[Chapter]]:
    if not chapters:
        return []

    console.print(
        "Enter a chapter number, a range (e.g. 1-5), comma-separated values, or 'all' to download everything."
    )

    while True:
        raw = typer.prompt("Chapter selection", default="all").strip()
        if not raw:
            continue
        lower = raw.lower()
        if lower in {"quit", "q", "exit"}:
            return None
        if lower in {"all", "*"}:
            return chapters

        tokens = [token.strip() for token in raw.split(",") if token.strip()]
        selected: List[Chapter] = []
        seen_ids: set[str] = set()
        for token in tokens:
            if "-" in token:
                subset = _select_chapters(chapters, None, token, False)
            else:
                subset = _select_chapters(chapters, token, None, False)
            for chapter in subset:
                if chapter.id not in seen_ids:
                    seen_ids.add(chapter.id)
                    selected.append(chapter)

        if selected:
            return selected

        typer.secho("No chapters matched that selection. Try again or type 'quit'.", fg=typer.colors.YELLOW)


def _chapter_display_name(chapter: Chapter) -> str:
    if chapter.number is not None:
        base = f"{chapter.number:g}"
        if chapter.title and chapter.title.lower().startswith("chapter"):
            return chapter.title
        if chapter.title:
            return f"{base} - {chapter.title}"
        return base
    return chapter.title or chapter.url


async def _run_download(
    manga: Manga,
    chapters: List[Chapter],
    output: Path,
    chapter_workers: int,
    image_workers: int,
    retries: int,
    backoff: float,
) -> List[Dict[str, Any]]:
    downloaded_chapters_info = []
    progress = Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )
    chapter_tasks: Dict[str, TaskID] = {}

    def handle_progress(event: str, payload: Dict[str, object]) -> None:
        ch: Chapter = payload["chapter"]  # type: ignore
        task_id = chapter_tasks.get(ch.id)

        if event == "chapter_started":
            description = f"Chapter {ch.number:g}" if ch.number is not None else ch.title
            total_pages = len(ch.pages) if ch.pages else 0
            chapter_tasks[ch.id] = progress.add_task(description or ch.url, total=total_pages)
        elif event == "page_completed":
            if task_id is not None:
                progress.advance(task_id, 1)
        elif event == "chapter_completed":
            if task_id is not None:
                progress.update(task_id, completed=progress.tasks[task_id].total or 0)
            downloaded_chapters_info.append({"chapter": ch, "path": payload["destination"]})
        elif event == "chapter_failed":
            if task_id is not None:
                progress.stop_task(task_id)
            typer.secho(f"Chapter failed: {ch.title}", fg=typer.colors.RED)

    with progress:
        async with ChapterDownloader(
            output_dir=output,
            max_chapter_workers=chapter_workers,
            max_image_workers=image_workers,
            retries=retries,
            backoff=backoff,
            progress_callback=handle_progress,
        ) as downloader:
            # Stage 1: Scrape pages
            scraping_task = progress.add_task("Scraping page information...", total=len(chapters))
            async with downloader.get_browser_context() as context:
                scrape_coroutines = [scrape_pages(ch, context) for ch in chapters]
                results = await asyncio.gather(*scrape_coroutines, return_exceptions=True)

            for i, result in enumerate(results):
                chapter = chapters[i]
                if isinstance(result, Exception):
                    typer.secho(f"Failed to scrape pages for {chapter.title}: {result}", fg=typer.colors.RED)
                    chapter.pages = []
                else:
                    if isinstance(result, list):
                        chapter.pages = result
                progress.advance(scraping_task)
            progress.update(scraping_task, visible=False)

            # Stage 2: Download
            chapters_to_download = [ch for ch in chapters if ch.pages]
            if chapters_to_download:
                await downloader.download(manga, chapters_to_download)

    return downloaded_chapters_info


def _perform_conversion(
    manga: Manga,
    downloaded_chapters: List[Dict[str, Any]],
    output_dir: Path,
    format: str,
    cleanup: bool,
) -> None:
    console.print(f"\n[bold]Converting {len(downloaded_chapters)} chapter(s) to {format.upper()}[/bold]")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Converting...", total=len(downloaded_chapters))

        for item in downloaded_chapters:
            chapter: Chapter = item["chapter"]
            chapter_path: Path = item["path"]
            
            progress.update(task, description=f"Converting chapter '{chapter.title}'")

            try:
                image_files = get_image_files(chapter_path)
                if not image_files:
                    console.print(f"[yellow]No images found for chapter {chapter.title}, skipping.[/yellow]")
                    progress.advance(task)
                    continue

                output_filename = f"{chapter_path.name}.{format}"
                output_file = output_dir / manga.id / output_filename
                
                if format == "pdf":
                    convert_to_pdf(image_files, output_file)
                elif format == "cbz":
                    convert_to_cbz(image_files, output_file)

                if cleanup:
                    cleanup_images(image_files)
                    try:
                        chapter_path.rmdir()
                    except OSError:
                        pass
            except (ConversionError, OSError) as exc:
                console.print(f"[red]Error converting chapter {chapter.title}: {exc}[/red]")
            
            progress.advance(task)
