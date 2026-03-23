import os
import pandas as pd
from booknlp.booknlp import BookNLP
from core.models import Book, Chapter, Paragraph
from core.nlp.paragraph_splitter import split_chapter_paragraphs, build_character_names


class BookNLPProcessor:

    def __init__(self):
        model_params = {
            "pipeline": "entity,quote,coref",
            "model": "small"
        }
        print("Load BookNLP...")
        self.nlp = BookNLP("en", model_params)
        print("BookNLP is ready!")

    def process_chapter(
        self,
        chapter: Chapter,
        work_dir: str,
        chapter_id: str
    ) -> Chapter:

        os.makedirs(work_dir, exist_ok=True)

        txt_path = os.path.join(work_dir, f"{chapter_id}.txt")
        full_text = "\n\n".join(p.text for p in chapter.paragraphs)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(full_text)

        self.nlp.process(txt_path, work_dir, chapter_id)

        quotes = pd.read_csv(
            os.path.join(work_dir, f"{chapter_id}.quotes"), sep="\t"
        )
        tokens = pd.read_csv(
            os.path.join(work_dir, f"{chapter_id}.tokens"), sep="\t"
        )
        entities_path = os.path.join(work_dir, f"{chapter_id}.entities")
        char_names = build_character_names(entities_path)

        new_paragraphs = split_chapter_paragraphs(
            chapter.paragraphs, quotes, tokens, char_names
        )

        chapter.paragraphs = new_paragraphs
        return chapter

    def process_book(self, book: Book, work_dir: str) -> Book:
        total = len(book.chapters)
        for i, chapter in enumerate(book.chapters):
            print(f"\n[{i+1}/{total}] {chapter.title}")
            chapter_id = f"chapter_{chapter.id}"
            book.chapters[i] = self.process_chapter(
                chapter,
                os.path.join(work_dir, chapter_id),
                chapter_id
            )
            narrations = sum(1 for p in book.chapters[i].paragraphs if p.type == "narration")
            dialogues  = sum(1 for p in book.chapters[i].paragraphs if p.type == "dialogue")
            print(f"  narration: {narrations}  💬 dialogue: {dialogues}")
        return book