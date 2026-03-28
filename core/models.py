from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Paragraph:
    text: str
    type: str
    chapter_id: int
    speaker: Optional[str] = None
    scene: Optional[str] = None


@dataclass
class Chapter:
    id: int
    title: str
    chapter_type: str
    paragraphs: List[Paragraph] = field(default_factory=list)


@dataclass
class Character:
    id: int
    name: str
    mentions: int
    voice_id: Optional[str] = None


@dataclass
class Book:
    title: str
    author: str
    language: str
    chapters: List[Chapter] = field(default_factory=list)
    characters: List[Character] = field(default_factory=list)

