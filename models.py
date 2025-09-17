from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass(slots=True)
class Page:
    index: int
    url: str
    filename: Optional[str] = None


@dataclass(slots=True)
class Chapter:
    id: str
    title: str
    url: str
    number: Optional[float] = None
    published_at: Optional[datetime] = None
    pages: List[Page] = field(default_factory=list)


@dataclass(slots=True)
class Manga:
    id: str
    title: str
    url: str
    cover_url: Optional[str] = None
    author: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    description: Optional[str] = None
    chapters: List[Chapter] = field(default_factory=list)
    total_chapters: Optional[int] = None
    last_updated: Optional[str] = None
