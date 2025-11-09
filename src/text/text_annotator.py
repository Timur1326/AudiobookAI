from transformers import pipeline
import spacy

class TextAnnotator:
    def __init__(self):
        self.nlp = spacy.load("en_core_web_sm")
        self.emotion_model = pipeline(
            "text-classification",
            model="j-hartmann/emotion-english-distilroberta-base"
        )

    def annotate(self, text: str):
        doc = self.nlp(text)
        annotated = []
        for sent in doc.sents:
            emotion = self.emotion_model(sent.text)[0]['label']
            pause = 0.6 if sent.text.endswith('.') else 0.3
            annotated.append({
                "text": sent.text,
                "emotion": emotion,
                "pause": pause,
                "rate": 1.0,
                "pitch": 0
            })
        return annotated