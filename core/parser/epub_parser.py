import re
import json
import os
import sys
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from typing import List

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from core.models import Book, Chapter, Paragraph

# ──────────────────────────────────────────
# Файлы которые пропускаем
# ──────────────────────────────────────────

SKIP_FILENAMES = ["toc", "wrap", "cover", "copyright",
                  "title", "colophon", "index", "nav"]

SKIP_CONTENT   = ["Project Gutenberg", "END OF THE PROJECT",
                  "gutenberg.org"]

# ──────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────

def should_skip(filename: str, raw: str) -> bool:
    if any(kw in filename.lower() for kw in SKIP_FILENAMES):
        return True
    if any(kw in raw[:300] for kw in SKIP_CONTENT):
        return True
    return False


def clean_text(text: str) -> str:
    text = re.sub(r'\s+', ' ', text)        # лишние пробелы
    text = re.sub(r'\[\d+\]', '', text)     # номера страниц [2]
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    return text.strip()


def get_chapter_title(element) -> str:
    """Ищем заголовок главы рядом с div.chapter"""
    text = element.get_text(strip=True)
    # Ищем следующий sidenote
    sidenote = element.find_next_sibling("div", class_="sidenote")
    if sidenote:
        subtitle = sidenote.get_text(separator=" ", strip=True)
        return f"{text} — {clean_text(subtitle)}"
    return text


# ──────────────────────────────────────────
# Извлечение текста из одного HTML файла
# ──────────────────────────────────────────

def extract_from_document(html_content: bytes, start_id: int) -> List[Chapter]:
    soup = BeautifulSoup(html_content, "html.parser")

    # Удаляем всё лишнее
    for tag in soup.find_all(["img", "figure", "svg",
                               "script", "style", "table"]):
        tag.decompose()
    for tag in soup.find_all("span", class_="x-ebookmaker-pageno"):
        tag.decompose()

    chapters: List[Chapter] = []
    current: Chapter = None
    chapter_id = start_id

    body = soup.find("body")
    if not body:
        return chapters

    for el in body.children:
        if not hasattr(el, "name") or not el.name:
            continue

        classes = el.get("class", [])

        # ── Новая глава ──────────────────────────────────
        if el.name == "div" and "chapter" in classes:
            heading = el.get_text(strip=True)

            # Сохраняем предыдущую
            if current and current.paragraphs:
                chapters.append(current)

            title = get_chapter_title(el)
            current = Chapter(
                id=chapter_id,
                title=title,
                chapter_type="chapter",
                paragraphs=[]
            )
            chapter_id += 1

        # ── Пропускаем sidenote (уже в заголовке) ────────
        elif el.name == "div" and "sidenote" in classes:
            continue

        # ── Текстовые блоки ──────────────────────────────
        elif el.name in ["p", "div"]:
            if current is None:
                continue

            # Пропускаем служебные классы
            skip_classes = ["figleft", "figright", "sidenote",
                            "center", "chapter", "footnote"]
            if any(c in classes for c in skip_classes):
                continue

            text = el.get_text(separator=" ", strip=True)
            text = clean_text(text)

            if len(text) < 10:
                continue

            current.paragraphs.append(Paragraph(
                text=text,
                type="text",
                chapter_id=current.id
            ))

    if current and current.paragraphs:
        chapters.append(current)

    return chapters


# ──────────────────────────────────────────
# Главная функция
# ──────────────────────────────────────────

def parse_epub(file_path: str) -> Book:
    epub_book = epub.read_epub(file_path)

    title   = epub_book.title or "Unknown"
    authors = epub_book.get_metadata("DC", "creator")
    author  = authors[0][0] if authors else "Unknown"
    lang    = epub_book.language or "en"

    book = Book(title=title, author=author, language=lang)

    chapter_id = 0
    for item in epub_book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        raw = item.get_content().decode("utf-8", errors="ignore")

        if should_skip(item.file_name, raw):
            print(f"  SKIP:  {item.file_name}")
            continue

        print(f"  PARSE: {item.file_name}")
        chapters = extract_from_document(item.get_content(), chapter_id)

        for ch in chapters:
            book.chapters.append(ch)
            print(f"    [{ch.id}] {ch.title} — {len(ch.paragraphs)} параграфов")
            chapter_id += 1

    return book


# ──────────────────────────────────────────
# JSON
# ──────────────────────────────────────────

def save_to_json(book: Book, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "title":          book.title,
        "author":         book.author,
        "language":       book.language,
        "total_chapters": len(book.chapters),
        "chapters": [
            {
                "id":               ch.id,
                "title":            ch.title,
                "type":             ch.chapter_type,
                "total_paragraphs": len(ch.paragraphs),
                "paragraphs": [
                    {
                        "text":       p.text,
                        "type":       p.type,        # narration / dialogue
                        "chapter_id": p.chapter_id,
                        "speaker":    p.speaker,     # Alice / Rabbit / None
                        "scene":      p.scene,
                    }
                    for p in ch.paragraphs
                ]
            }
            for ch in book.chapters
        ]
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Сохранено: {path}  ({len(book.chapters)} глав)")


def load_from_json(path: str) -> Book:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    book = Book(
        title=data["title"],
        author=data["author"],
        language=data["language"]
    )
    for ch_data in data["chapters"]:
        ch = Chapter(
            id=ch_data["id"],
            title=ch_data["title"],
            chapter_type=ch_data["type"]
        )
        for p in ch_data["paragraphs"]:
            ch.paragraphs.append(Paragraph(
                text=p["text"],
                type=p["type"],
                chapter_id=p["chapter_id"],
                speaker=p.get("speaker"),
                scene=p.get("scene")
            ))
        book.chapters.append(ch)
    return book