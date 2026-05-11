"""Intermediate dataclasses used during EPUB parsing (before data is written to DB)."""

from dataclasses import dataclass, field


@dataclass
class Paragraph:
    text: str
    type: str
    chapter_id: int
    speaker: str | None = None


@dataclass
class Chapter:
    id: int
    title: str
    chapter_type: str
    paragraphs: list[Paragraph] = field(default_factory=list)


@dataclass
class Book:
    title: str
    author: str
    language: str
    chapters: list[Chapter] = field(default_factory=list)