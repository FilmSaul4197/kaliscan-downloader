from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Coroutine, Iterable, List, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import BrowserContext

from models import Chapter, Manga, Page
from utils import DEFAULT_HEADERS, get_logger, sanitize_filename

__all__ = [
    "ScraperError",
    "scrape_manga",
    "scrape_chapters",
    "scrape_pages",
]


class ScraperError(RuntimeError):
    """Raised when Kaliscan pages cannot be scraped."""


_logger = get_logger(__name__)


async def _fetch(url: str, client: Optional[httpx.AsyncClient] = None) -> str:
    close_client = False
    if client is None:
        client = httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=30.0)
        close_client = True
    try:
        response = await client.get(url)
        response.raise_for_status()
        return response.text
    except httpx.HTTPError as exc:
        raise ScraperError(f"Failed to fetch {url}: {exc}") from exc
    finally:
        if close_client and client:
            await client.aclose()


async def scrape_manga(url: str, client: Optional[httpx.AsyncClient] = None) -> Manga:
    html = await _fetch(url, client)
    soup = BeautifulSoup(html, "lxml")

    title = _extract_title(soup)
    if not title:
        _logger.warning("Falling back to URL-derived title because page provided none")
        title = sanitize_filename(url.rstrip("/").split("/")[-1])

    manga_id = sanitize_filename(title.lower())
    cover_url = _extract_cover(soup, base_url=url)
    author = _extract_author(soup)
    description = _extract_description(soup)
    tags = _extract_tags(soup)
    total_chapters = _extract_total_chapters(soup)
    last_updated = _extract_last_updated(soup)

    manga = Manga(
        id=manga_id,
        title=title,
        url=url,
        cover_url=cover_url,
        author=author,
        tags=tags,
        description=description,
        total_chapters=total_chapters,
        last_updated=last_updated,
    )

    chapters = await scrape_chapters(url, client=client, soup=soup)
    manga.chapters = chapters
    return manga


async def scrape_chapters(
    manga_url: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
    soup: Optional[BeautifulSoup] = None,
) -> List[Chapter]:
    if soup is None:
        html = await _fetch(manga_url, client)
        soup = BeautifulSoup(html, "lxml")

    chapter_links = list(_iter_chapter_links(soup, base_url=manga_url))
    if not chapter_links:
        raise ScraperError("Unable to locate chapter list on the provided manga page")

    chapters: List[Chapter] = []
    for idx, meta in enumerate(chapter_links, start=1):
        title = meta.get("title") or f"Chapter {idx}"
        number = meta.get("number")
        chapter_id = sanitize_filename(meta.get("id") or f"{number or idx}-{title}")
        chapters.append(
            Chapter(
                id=chapter_id,
                title=title,
                url=meta["url"],
                number=number,
                published_at=meta.get("published_at"),
            )
        )

    chapters.sort(key=lambda ch: (ch.number if ch.number is not None else float("inf"), ch.title))
    return chapters


async def scrape_pages(chapter: Chapter, browser_context: BrowserContext) -> List[Page]:
    page = await browser_context.new_page()
    try:
        await page.goto(chapter.url, wait_until="domcontentloaded", timeout=60000)

        # Handle the warning accept button if it appears
        try:
            # Increased timeout for the warning button
            await page.wait_for_selector("button.btn.btn-warning", timeout=10000)
            await page.click("button.btn.btn-warning")
            # Wait for any potential redirect or content change after clicking
            await page.wait_for_load_state("networkidle")
            _logger.info("Clicked Accept button on chapter page")
        except Exception:
            _logger.debug("No warning button found on chapter page, continuing...")

        # Wait for chapter images to be present
        await page.wait_for_selector("div.chapter-image", timeout=15000)

        image_divs = await page.query_selector_all("div.chapter-image")
        if not image_divs:
            raise ScraperError(f"Unable to locate page images for chapter {chapter.title}")

        pages_data: List[Page] = []
        for i, div in enumerate(image_divs, start=1):
            img_url = await div.get_attribute("data-src")
            if not img_url:
                img_tag = await div.query_selector("img")
                if img_tag:
                    img_url = await img_tag.get_attribute("src")

            if img_url:
                pages_data.append(Page(index=i, url=img_url))
            else:
                _logger.warning("Could not extract image URL for page %d in chapter %s", i, chapter.title)
        return pages_data
    finally:
        await page.close()


def _extract_title(soup: BeautifulSoup) -> Optional[str]:
    name_heading = soup.select_one("div.book-info div.detail div.name h1")
    if name_heading:
        text = name_heading.get_text(strip=True)
        if text:
            return text
    selectors = [
        "meta[property='og:title']",
        "meta[name='title']",
        "h1",
        "title",
    ]
    for selector in selectors:
        element = soup.select_one(selector)
        if element is None:
            continue
        text = element.get("content") if element_has_content(element) else element.get_text(strip=True)
        if text:
            return text.strip()
    return None


def _extract_cover(soup: BeautifulSoup, *, base_url: str) -> Optional[str]:
    cover_img = soup.select_one("div.img-cover img")
    if cover_img:
        src = cover_img.get("data-src") or cover_img.get("src")
        if src:
            return urljoin(base_url, src)
    candidates = [
        soup.select_one("meta[property='og:image']"),
        soup.select_one("img.cover"),
        soup.select_one("img[src*='cover']"),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        src = candidate.get("content") or candidate.get("src")
        if src:
            return urljoin(base_url, src)
    return None


def _extract_author(soup: BeautifulSoup) -> Optional[str]:
    author_element = soup.select_one("p:-soup-contains('Authors') a")
    if author_element:
        return author_element.get_text(strip=True)

    selectors = [
        "span.author",
        "a[href*='author']",
        "div.book-info div.meta p:-soup-contains('Author')",
        "div.author",
        "li:-soup-contains('Author')",
    ]
    for selector in selectors:
        element = soup.select_one(selector)
        if element is None:
            continue
        text = element.get_text(strip=True)
        if text:
            text = re.sub(r"(?i)author:?\s*", "", text, flags=re.IGNORECASE)
            return text.strip()
    return None


def _extract_description(soup: BeautifulSoup) -> Optional[str]:
    description_block = soup.select_one("div.book-info div.detail div#summary")
    if description_block:
        text = description_block.get_text(" ", strip=True)
        if text:
            return text
    candidates = [
        soup.select_one("meta[name='description']"),
        soup.select_one("div.description"),
        soup.select_one("p.description"),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        text = candidate.get("content") if element_has_content(candidate) else candidate.get_text(" ", strip=True)
        if text:
            return text.strip()
    return None


def element_has_content(element: Any) -> bool:
    return hasattr(element, "has_attr") and element.has_attr("content")


def _extract_tags(soup: BeautifulSoup) -> List[str]:
    tags: List[str] = []
    genre_section = soup.select_one("div.book-info div.meta p:has(strong:-soup-contains('Genres'))")
    if genre_section:
        for link in genre_section.find_all("a"):
            text = link.get_text(strip=True)
            text = text.rstrip(",")
            if text:
                tags.append(text)
    for selector in ("a.tag", "span.tag", "li.tag"):
        tags.extend(element.get_text(strip=True) for element in soup.select(selector))
    deduped: List[str] = []
    seen: set[str] = set()
    for tag in tags:
        normalized = tag.lower()
        if normalized and normalized not in seen:
            deduped.append(tag)
            seen.add(normalized)
    return deduped


def _iter_chapter_links(soup: BeautifulSoup, *, base_url: str) -> Iterable[dict[str, Any]]:
    explicit_nodes = soup.select("div#chapter-list-inner ul.chapter-list li")
    seen_urls: set[str] = set()
    if explicit_nodes:
        for node in explicit_nodes:
            anchor = node.find("a", href=True)
            if not anchor:
                continue
            href = urljoin(base_url, anchor["href"])
            if href in seen_urls:
                continue
            seen_urls.add(href)

            title = anchor.get("title")
            title = title or _extract_text(node.select_one("strong.chapter-title")) or anchor.get_text(" ", strip=True)
            time_node = node.find("time", class_="chapter-update")
            published_at = None
            if time_node:
                if time_node.has_attr("datetime"):
                    published_at = _parse_datetime(time_node["datetime"])
                else:
                    published_at = _parse_datetime(time_node.get_text(strip=True))

            yield {
                "url": href,
                "title": title,
                "number": _parse_chapter_number(title) or _parse_chapter_number(anchor.get("data-number")),
                "published_at": published_at,
                "id": node.get("id"),
            }


def _extract_text(node: Any) -> Optional[str]:
    if node is None:
        return None
    return node.get_text(" ", strip=True)


def _parse_chapter_number(text: str | None) -> Optional[float]:
    if not text:
        return None
    match = re.search(r"(?i)(?:chapter|ch\.)\s*([0-9]+(?:\.[0-9]+)?)", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _parse_datetime(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    relative = _parse_relative(value)
    if relative:
        return relative

    return None


def _parse_relative(value: str) -> Optional[datetime]:
    match = re.match(r"(?i)(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", value)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    delta = None
    if unit == "second":
        delta = timedelta(seconds=amount)
    elif unit == "minute":
        delta = timedelta(minutes=amount)
    elif unit == "hour":
        delta = timedelta(hours=amount)
    elif unit == "day":
        delta = timedelta(days=amount)
    elif unit == "week":
        delta = timedelta(weeks=amount)
    elif unit == "month":
        delta = timedelta(days=30 * amount)
    elif unit == "year":
        delta = timedelta(days=365 * amount)

    if delta is None:
        return None
    return datetime.now(timezone.utc) - delta


def _extract_total_chapters(soup: BeautifulSoup) -> Optional[int]:
    chapters_element = soup.select_one("p:-soup-contains('Chapters') span")
    if chapters_element:
        text = chapters_element.get_text(strip=True)
        if text.isdigit():
            return int(text)
    return None


def _extract_last_updated(soup: BeautifulSoup) -> Optional[str]:
    update_element = soup.select_one("p:-soup-contains('Last update') span")
    if update_element:
        return update_element.get_text(strip=True)
    return None
