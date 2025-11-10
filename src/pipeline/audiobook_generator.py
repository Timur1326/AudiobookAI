import json
from src.tts.azure_tts_engine import AzureTTSEngine
from src.text.text_annotator import TextAnnotator
from src.tts.audio_mixer import AudioMixer

class AudiobookGenerator:
    def __init__(self, input_text_path, azure_key, azure_region):
        self.text_annotator = TextAnnotator()
        self.tts = AzureTTSEngine(azure_key, azure_region, voice="en-US-AriaNeural")
        self.input_text_path = input_text_path

    def run(self, output_path="data/output.wav"):
        # Читаем книгу
        with open(self.input_text_path, "r", encoding="utf-8") as f:
            text = f.read()

        annotated = self.text_annotator.annotate(text)
        with open("data/annotated_text.json", "w", encoding="utf-8") as f:
            json.dump(annotated, f, ensure_ascii=False, indent=2)
        print("Annotated text saved to data/annotated_text.json")

        for i, seg in enumerate(annotated):
            emotion = seg.get("emotion", "narration-professional")
            rate = seg.get("rate", "+0%")
            pitch = seg.get("pitch", "+0Hz")

            out_file = f"data/segment_{i}.wav"
            self.tts.synthesize(seg["text"], out_file, emotion=emotion)

        print("[✔] Audiobook generation completed.")

        segment_paths = [f"data/segment_{i}.wav" for i in range(len(annotated))]

        # Инициализация микшера
        mixer = AudioMixer(sample_rate=24000)

        # Склейка всех сегментов
        mixed = mixer.mix(segment_paths, annotations=annotated)

        # Экспорт объединённого файла
        mixer.export(mixed, "data/output.wav")