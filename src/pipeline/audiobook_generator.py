from src.text.text_loader import TextLoader
from src.text.text_annotator import TextAnnotator
from src.tts.tts_engine import TTSEngine
from src.tts.audio_mixer import AudioMixer
import json

class AudiobookGenerator:
    def __init__(self, text_path, ref_voice):
        self.loader = TextLoader(text_path)
        self.annotator = TextAnnotator()
        self.tts = TTSEngine()
        self.mixer = AudioMixer()
        self.tts.set_voice(ref_voice)

    def run(self, output_path="output.wav"):
        text = self.loader.clean(self.loader.load())
        annotated = self.annotator.annotate(text)

        # 📁 сохраняем аннотированный текст в JSON
        annotated_path = "data/annotated_text.json"
        with open(annotated_path, "w", encoding="utf-8") as f:
            json.dump(annotated, f, indent=2, ensure_ascii=False)

        print(f"[💾] Annotated text saved to {annotated_path}")

        # # 🔊 продолжаем генерацию речи
        # segments = self.tts.synthesize(annotated)
        # mixed = self.mixer.mix(segments, annotated)
        # self.mixer.export(mixed, output_path)

        # print(f"[✔] Audiobook saved as {output_path}")