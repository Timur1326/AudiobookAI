import numpy as np
import soundfile as sf
import os

class AudioMixer:
    def __init__(self, sample_rate=None):
        """
        Если sample_rate=None — частота будет автоматически определена
        по первому сегменту.
        """
        self.sample_rate = sample_rate

    def mix(self, segment_paths, annotations=None, default_pause=0.4):
        mixed = np.array([], dtype=np.float32)

        for i, path in enumerate(segment_paths):
            if not os.path.exists(path):
                print(f"[⚠️] Segment not found: {path}")
                continue

            data, sr = sf.read(path, dtype='float32')

            # если sample_rate не задан — подстроимся под первый сегмент
            if self.sample_rate is None:
                self.sample_rate = sr
                print(f"[ℹ️] Detected sample rate from first segment: {self.sample_rate} Hz")

            # если вдруг другие сегменты отличаются — ресемплим
            if sr != self.sample_rate:
                import librosa
                print(f"[↻] Resampling {path} from {sr} → {self.sample_rate}")
                data = librosa.resample(data, orig_sr=sr, target_sr=self.sample_rate)

            # добавляем сегмент
            mixed = np.concatenate((mixed, data))

            # добавляем паузу
            pause_duration = annotations[i].get("pause", default_pause) if annotations else default_pause
            silence = np.zeros(int(pause_duration * self.sample_rate), dtype=np.float32)
            mixed = np.concatenate((mixed, silence))

        return mixed

    def export(self, mixed, path="data/output.wav"):
        sf.write(path, mixed, self.sample_rate)
        print(f"[🎧] Exported final audio → {path}")