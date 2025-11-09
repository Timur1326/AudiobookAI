from transformers import pipeline
import spacy
from spacy.language import Language

@Language.component("quote_sentence_boundary")
def quote_sentence_boundary(doc):
    """
    Кастомный компонент: помогает разбивать диалоги с кавычками,
    но не создаёт кавычки как отдельные предложения.
    """
    for i, token in enumerate(doc[:-2]):
        # Если есть вопрос/восклицание перед кавычкой и новой репликой — делаем разрыв
        if token.text in ['?', '!']:
            next_token = doc[i + 1]
            next2_token = doc[i + 2]
            if next_token.text in ['"', '”'] and next2_token.text[0].isupper():
                doc[next2_token.i].is_sent_start = True

        # Если кавычка закрывается и потом идёт заглавная — это новое предложение
        if token.text in ['"', '”'] and token.nbor(1).text[0].isupper():
            doc[token.nbor(1).i].is_sent_start = True

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
        annotated = []

        for sent in doc.sents:
            cleaned_text = sent.text.strip()

            # 🔥 Игнорируем пустые и "мусорные" предложения (одни кавычки, тире и т.п.)
            if not cleaned_text or cleaned_text in ['"', '“', '”', "'", "-", "–"]:
                continue

            result = self.emotion_model(cleaned_text)[0]
            emotion = result["label"].lower().strip()
            score = result["score"]

            if score < 0.4 or emotion not in self.supported_emotions:
                emotion = "neutral"

            last_char = cleaned_text[-1] if cleaned_text else ""
            if last_char in [".", "!", "?"]:
                pause = 0.6
            elif last_char in [",", ";", ":"]:
                pause = 0.35
            else:
                pause = 0.25

            annotated.append({
                "text": cleaned_text,
                "emotion": emotion,
                "pause": round(pause, 2),
                "rate": 1.0,
                "pitch": 0
            })

        print(f"[📝] Annotated {len(annotated)} sentences (cleaned).")
        return annotated