from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Paragraph:
    text: str
    type: str  # "text" | "dialogue" | "heading"
    chapter_id: int
    speaker: Optional[str] = None  # who says this (from BookNLP)
    scene: Optional[str] = None  # background scene type


@dataclass
class Chapter:
    id: int
    title: str
    chapter_type: str  # "chapter" | "preface" | "introduction" | "epilogue"
    paragraphs: List[Paragraph] = field(default_factory=list)


@dataclass
class Character:
    id: int
    name: str
    mentions: int
    voice_id: Optional[str] = None  # assigned TTS voice


@dataclass
class Book:
    title: str
    author: str
    language: str
    chapters: List[Chapter] = field(default_factory=list)
    characters: List[Character] = field(default_factory=list)

