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


SKIP_FILENAMES = ["toc", "wrap", "cover", "copyright",
                  "title", "colophon", "index", "nav"]

SKIP_CONTENT   = ["Project Gutenberg", "END OF THE PROJECT",
                  "gutenberg.org"]



def should_skip(filename: str, raw: str) -> bool:
    if any(kw in filename.lower() for kw in SKIP_FILENAMES):
        return True
    if any(kw in raw[:300] for kw in SKIP_CONTENT):
        return True
    return False


def clean_text(text: str) -> str:
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\[\d+\]', '', text)
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    return text.strip()


def get_chapter_title(element) -> str:
    text = element.get_text(strip=True)
    sidenote = element.find_next_sibling("div", class_="sidenote")
    if sidenote:
        subtitle = sidenote.get_text(separator=" ", strip=True)
        return f"{text} — {clean_text(subtitle)}"
    return text


def extract_h2_chapter_title(element) -> str:

    raw = element.get_text(separator="\n", strip=True)
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    for line in reversed(lines):
        if re.search(r"chapter", line, re.IGNORECASE):
            return clean_text(line)
    return clean_text(lines[-1]) if lines else ""


def is_chapter_heading(element) -> bool:
    if element.name == "div" and "chapter" in element.get("class", []):
        return True
    if element.name == "h1":
        return True
    if element.name in ("h2", "h3") and re.search(
        r"chapter", element.get_text(), re.IGNORECASE
    ):
        return True
    return False


def _iter_body_elements(body):
    """Yield relevant elements, flattening only <section> wrappers."""
    for el in body.children:
        if not hasattr(el, "name") or not el.name:
            continue
        if el.name == "section":
            yield from _iter_body_elements(el)
        else:
            yield el


def extract_from_document(html_content: bytes, start_id: int) -> List[Chapter]:
    soup = BeautifulSoup(html_content, "html.parser")

    for img in soup.find_all("img"):
        alt = img.get("alt", "")
        if len(alt) == 1 and alt.isalpha():
            img.replace_with(alt)
        else:
            img.decompose()

    for tag in soup.find_all(["figure", "svg", "script", "style", "table"]):
        tag.decompose()
    for tag in soup.find_all("span", class_="x-ebookmaker-pageno"):
        tag.decompose()

    chapters: List[Chapter] = []
    current: Chapter = None
    chapter_id = start_id
    drop_cap_prefix = ""

    body = soup.find("body")
    if not body:
        return chapters

    for el in _iter_body_elements(body):
        if not hasattr(el, "name") or not el.name:
            continue

        classes = el.get("class", [])

        # Handle <div class="chapter"> as a self-contained chapter block
        if el.name == "div" and "chapter" in classes:
            if current and current.paragraphs:
                chapters.append(current)

            title_el = el.find(["h1", "h2", "h3"])
            if title_el:
                title = clean_text(title_el.get_text(separator=" ", strip=True))
            else:
                title = f"Chapter {chapter_id}"

            current = Chapter(
                id=chapter_id,
                title=title,
                chapter_type="chapter",
                paragraphs=[]
            )
            chapter_id += 1

            for p_el in el.find_all("p"):
                p_classes = p_el.get("class", [])
                skip_cls = ["sidenote", "center", "footnote", "caption"]
                if any(c in p_classes for c in skip_cls):
                    continue
                text = clean_text(p_el.get_text(separator=" ", strip=True))
                if drop_cap_prefix:
                    text = drop_cap_prefix + text
                    drop_cap_prefix = ""
                if len(text) < 10:
                    continue
                current.paragraphs.append(Paragraph(
                    text=text,
                    type="text",
                    chapter_id=current.id
                ))

            continue

        if is_chapter_heading(el):
            if current and current.paragraphs:
                chapters.append(current)

            if el.name in ("h2", "h3"):
                title = extract_h2_chapter_title(el)
            else:
                title = get_chapter_title(el)

            current = Chapter(
                id=chapter_id,
                title=title,
                chapter_type="chapter",
                paragraphs=[]
            )
            chapter_id += 1

        elif el.name == "div" and "sidenote" in classes:
            continue

        elif el.name == "div" and any(c in classes for c in ["figleft", "figright"]):
            letter = el.get_text(strip=True)
            if len(letter) == 1 and letter.isalpha():
                drop_cap_prefix = letter
            continue

        elif el.name in ["p", "div"]:
            if current is None:
                continue

            skip_classes = ["sidenote", "center", "chapter", "footnote", "caption"]
            if any(c in classes for c in skip_classes):
                continue

            text = el.get_text(separator=" ", strip=True)
            text = clean_text(text)

            if drop_cap_prefix:
                text = drop_cap_prefix + text
                drop_cap_prefix = ""

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
                        "speaker":    p.speaker,
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


def extract_cover(epub_path: str, dest_dir: str) -> str | None:
    """
    Extract cover image from EPUB and save to dest_dir/cover.jpg (or .png).
    Returns the saved path, or None if no cover found.
    """
    import mimetypes
    epub_book = epub.read_epub(epub_path)

    # Try common cover item IDs
    cover_item = None
    for item_id in ("cover-image", "cover", "Cover", "CoverImage"):
        cover_item = epub_book.get_item_with_id(item_id)
        if cover_item:
            break

    # Fallback: find first image item with "cover" in name
    if not cover_item:
        for item in epub_book.get_items_of_type(ebooklib.ITEM_IMAGE):
            if "cover" in item.file_name.lower():
                cover_item = item
                break

    # Fallback: find cover via metadata
    if not cover_item:
        meta = epub_book.get_metadata("OPF", "cover")
        if meta:
            cover_id = meta[0][1].get("content") if meta[0][1] else None
            if cover_id:
                cover_item = epub_book.get_item_with_id(cover_id)

    if not cover_item:
        return None

    content = cover_item.get_content()
    media_type = cover_item.media_type or "image/jpeg"
    ext = mimetypes.guess_extension(media_type) or ".jpg"
    if ext == ".jpe":
        ext = ".jpg"

    out_path = os.path.join(dest_dir, f"cover{ext}")
    with open(out_path, "wb") as f:
        f.write(content)
    return out_path


def parse_epub_to_db(epub_path: str, book_id: int, db) -> int:
    """
    Parse EPUB and write chapters + paragraphs directly to the database.
    Returns total number of paragraphs inserted.

    DB models are imported here to keep core/ free of backend dependencies
    at import time — only needed when actually calling this function.
    """
    from backend.models import (
        Chapter as DBChapter,
        Paragraph as DBParagraph,
    )

    parsed = parse_epub(epub_path)
    total_paragraphs = 0

    # Extract cover image
    book_dir = os.path.dirname(epub_path)
    extract_cover(epub_path, book_dir)

    for idx, ch in enumerate(parsed.chapters):
        db_chapter = DBChapter(
            book_id=book_id,
            chapter_index=idx,
            chapter_id=ch.id,
            title=ch.title,
        )
        db.add(db_chapter)
        db.flush()  # get db_chapter.id

        for i, p in enumerate(ch.paragraphs):
            db.add(DBParagraph(
                chapter_id=db_chapter.id,
                index=i,
                text=p.text,
                type="narration",   # default; quote_splitter will update
                speaker=None,
            ))
            total_paragraphs += 1

    return total_paragraphs