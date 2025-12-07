from transformers import pipeline
import spacy
from spacy.language import Language
import re

@Language.component("quote_sentence_boundary")
def quote_sentence_boundary(doc):
    """
    Кастомный компонент: корректно разбивает диалоги с кавычками.
    Не создаёт кавычки как отдельные предложения.
    """
    for i, token in enumerate(doc[:-2]):
        if token.text in ['?', '!']:
            next_token = doc[i + 1]
            next2_token = doc[i + 2]
            if next_token.text in ['"', '"'] and next2_token.text[0].isupper():
                doc[next2_token.i].is_sent_start = True

        if token.text in ['"', '"'] and token.i + 1 < len(doc):
            next_token = token.nbor(1)
            if next_token.text and next_token.text[0].isupper():
                doc[next_token.i].is_sent_start = True

    return doc


class TextAnnotator:
    def __init__(self):
        print("[🧠] Loading spaCy and emotion model...")
        self.nlp = spacy.load("en_core_web_sm")
        self.nlp.add_pipe("quote_sentence_boundary", before="parser")

        self.emotion_model = pipeline(
            "text-classification",
            model="j-hartmann/emotion-english-distilroberta-base",
            return_all_scores=False
        )

        self.supported_emotions = {
            "anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise"
        }

    def annotate(self, text: str):
        doc = self.nlp(text)
        sentences = [re.sub(r'\s+', ' ', s.text.strip()) for s in doc.sents]
        annotated = []
        TRASH_TOKENS = {'"', '"', '"', "'", "-", "–", "—"}

        for i, sent_text in enumerate(sentences):
            if not sent_text or sent_text in TRASH_TOKENS:
                continue
            if not re.search(r'[A-Za-z0-9]', sent_text):
                continue

            # Context window
            prev_sent = sentences[i - 1] if i > 0 else ""
            next_sent = sentences[i + 1] if i + 1 < len(sentences) else ""
            context_text = f"{prev_sent} {sent_text} {next_sent}".strip()

            result = self.emotion_model(context_text)[0]
            emotion = result["label"].lower().strip()
            score = result["score"]

            if score < 0.4 or emotion not in self.supported_emotions:
                emotion = "neutral"

            last_char = sent_text[-1] if sent_text else ""
            if last_char in [".", "!", "?"]:
                pause = 0.6
            elif last_char in [",", ";", ":"]:
                pause = 0.35
            else:
                pause = 0.25

            annotated.append({
                "text": sent_text,
                "emotion": emotion,
                "pause": round(pause, 2),
                "rate": 1.0,
                "pitch": 0
            })

        print(f"[📝] Annotated {len(annotated)} sentences with context window.")
        return annotated
