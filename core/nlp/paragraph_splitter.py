import re
import pandas as pd
from typing import List, Dict
from core.models import Paragraph


PRONOUNS = {
    "he", "she", "they", "him", "her", "them",
    "his", "hers", "their", "it", "its",
    "i", "me", "my", "we", "us", "our",
    "He", "She", "They", "Him", "Her", "Them",
    "His", "Hers", "Their", "It", "Its",
    "I", "Me", "My", "We", "Us", "Our"
}


def clean_narrator(text: str) -> str:
    text = re.sub(r'\s*[""\']\s*$', '', text)
    text = re.sub(r'^\s*[""\']\s*', '', text)
    return text.strip()


def build_character_names(entities_path: str) -> Dict[int, str]:

    entities = pd.read_csv(entities_path, sep="\t", quoting=3, on_bad_lines="skip")
    persons = entities[entities["cat"] == "PER"].copy()

    priority = {"PROP": 0, "NOM": 1, "PRON": 2}
    char_names: Dict[int, tuple] = {}

    for _, row in persons.iterrows():
        char_id = int(row["COREF"])
        prop    = row["prop"]
        text    = str(row["text"]).strip()

        if text.lower() in {p.lower() for p in PRONOUNS}:
            continue

        score = priority.get(prop, 3)
        if char_id not in char_names:
            char_names[char_id] = (score, text)
        else:
            existing_score, _ = char_names[char_id]
            if score < existing_score:
                char_names[char_id] = (score, text)

    return {cid: name for cid, (_, name) in char_names.items()}


def resolve_speaker(
    mention_phrase: str,
    char_id: int,
    char_names: Dict[int, str]
) -> str:

    phrase = mention_phrase.strip()

    if phrase.lower() in {p.lower() for p in PRONOUNS}:
        if char_id in char_names:
            return char_names[char_id]
        return phrase

    return _clean_speaker(phrase)


def split_paragraph_by_quotes(
    para: Paragraph,
    para_text: str,
    quotes_df: pd.DataFrame,
    tokens_df: pd.DataFrame,
    para_char_start: int,
    char_names: Dict[int, str],
) -> List[Paragraph]:

    para_len = len(para_text)
    para_char_end = para_char_start + para_len

    relevant_quotes = []
    for _, q in quotes_df.iterrows():
        q_start  = q["quote_start"]
        q_end    = q["quote_end"]
        char_id  = int(q["char_id"])

        q_tokens = tokens_df[
            (tokens_df["token_ID_within_document"] >= q_start) &
            (tokens_df["token_ID_within_document"] <= q_end)
        ]
        if q_tokens.empty:
            continue

        byte_start = int(q_tokens.iloc[0]["byte_onset"])
        byte_end   = int(q_tokens.iloc[-1]["byte_onset"]) + len(str(q_tokens.iloc[-1]["word"]))

        if byte_start >= para_char_start and byte_end <= para_char_end:
            local_start    = byte_start - para_char_start
            local_end      = byte_end   - para_char_start
            mention_phrase = str(q["mention_phrase"])

            speaker = resolve_speaker(mention_phrase, char_id, char_names)
            relevant_quotes.append((local_start, local_end, speaker))

    if not relevant_quotes:
        para.type = "narration"
        return [para]

    relevant_quotes.sort(key=lambda x: x[0])

    parts: List[Paragraph] = []
    cursor = 0

    for (q_start, q_end, speaker) in relevant_quotes:
        before = clean_narrator(para_text[cursor:q_start].strip())
        if len(before) > 5:
            parts.append(Paragraph(
                text=before,
                type="narration",
                chapter_id=para.chapter_id,
                speaker=None,
                scene=para.scene
            ))

        quote_text = para_text[q_start:q_end].strip()
        quote_text = quote_text.strip('"').strip('"').strip('"').strip()
        if len(quote_text) > 2:
            parts.append(Paragraph(
                text=quote_text,
                type="dialogue",
                chapter_id=para.chapter_id,
                speaker=speaker,
                scene=para.scene
            ))

        cursor = q_end

    after = clean_narrator(para_text[cursor:].strip())
    if len(after) > 5:
        parts.append(Paragraph(
            text=after,
            type="narration",
            chapter_id=para.chapter_id,
            speaker=None,
            scene=para.scene
        ))

    if not parts:
        para.type = "narration"
        return [para]
    return parts


def _clean_speaker(name: str) -> str:
    words = name.strip().split()
    stopwords = {"poor", "little", "the", "a", "an", "young", "old"}
    cleaned = [w for w in words if w.lower() not in stopwords]
    return " ".join(cleaned) if cleaned else name


def split_chapter_paragraphs(
    paragraphs: List[Paragraph],
    quotes_df: pd.DataFrame,
    tokens_df: pd.DataFrame,
    char_names: Dict[int, str],
) -> List[Paragraph]:

    offsets = []
    pos = 0
    texts = [p.text for p in paragraphs]
    for text in texts:
        offsets.append(pos)
        pos += len(text) + 2

    result: List[Paragraph] = []

    for i, para in enumerate(paragraphs):
        parts = split_paragraph_by_quotes(
            para=para,
            para_text=texts[i],
            quotes_df=quotes_df,
            tokens_df=tokens_df,
            para_char_start=offsets[i],
            char_names=char_names,
        )
        result.extend(parts)

    return result